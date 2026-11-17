"""試験の道具: Windows でも POSIX と同じ入力のバイト列と、同じ考え方の時間の上限で確かめるための関数。

yomiyasu のスクリプトは読み込まない（試験のファイルが import して使う）。

- run_text: subprocess.run の text モード（encoding、errors、text）の代わり。text モードの標準入力は、Windows では
  「\\n」を「\\r\\n」に、「\\r\\n」を「\\r\\r\\n」にして子に渡すので、文字列の入力を改行を変えずにバイト列にして渡す。
  出力の読み方は text モードと同じ（POSIX で text モードを使ったときと同じ文字列になる）。
- timing_clock、paced_limit: 子プロセスを使わない性能の試験の時計と上限。Windows では、秒数の上限を、基準の処理（このファイルの
  pace）の遅さの比で延ばす（速い機械でも上限は縮めない）。POSIX では延ばさず、2.1.2 までと同じ固定の上限で比べる。
"""

from bisect import bisect_left
from collections import Counter
import difflib
import re
import subprocess
import sys
import time


def text_output(data, encoding="utf-8", errors="strict"):
    """子の出力のバイト列を、subprocess の text モードと同じく読む（encoding で解き、CRLF と CR を LF にそろえる）。"""
    return data.decode(encoding, errors).replace("\r\n", "\n").replace("\r", "\n")


def run_text(command, input=None, encoding="utf-8", errors="strict", **kwargs):
    """subprocess.run(command, input=input, encoding=encoding, errors=errors, **kwargs) と同じ結果を返す。違いは、文字列の
    input を改行を変えずに encoding のバイト列にして渡すことだけ。標準出力と標準エラーは、捕まえたときは text_output で
    文字列にする。"""
    if isinstance(input, str):
        input = input.encode(encoding, errors)
    process = subprocess.run(command, input=input, **kwargs)
    for name in ("stdout", "stderr"):
        data = getattr(process, name)
        if isinstance(data, bytes):
            setattr(process, name, text_output(data, encoding, errors))
    return process


def timing_clock():
    """性能の試験の時計。CPU 時間で測る（ほかのプロセスに CPU を譲って待った時間を入れない）。Windows の CPU 時間は
    刻みが粗い（約16ミリ秒）ので、壁時計で測る。"""
    return time.perf_counter if sys.platform == "win32" else time.process_time


# pace の CPU 時間。Apple M5 Pro の Python 3.14.5 で、ほかの処理が少ないときに子プロセスで測った最小（0.059秒。v2.0.2）。
# ほかの処理が多いときは 0.08〜0.10秒になる。pace の中身を変えたら測り直す
PACE_SECONDS = 0.060

# pace は yomiyasu を使わない、量の決まった計算。difflib の照合、正規表現で文と数を拾って数える処理、関数の呼び出しの多い
# 走査、dict と二分探索を同じくらいずつ動かし、機械と Python の速さを測る
PACE_OLD = "".join("第%d項の値は%d件です。" % (i, i * 7 % 1000) for i in range(100))
PACE_NEW = "".join("第%d項の値は%d件でした。" % (i, i * 11 % 1000) for i in range(100))
PACE_TEXT = "".join("設定ファイル%dの値は%d件です。担当者は%d番目の結果を残し、会議で共有します。" % (i, i * 3, i % 97)
                    for i in range(1500))
PACE_SENTENCE = re.compile(r"[^。]*。")
PACE_NUMBER = re.compile(r"[0-9]+(?P<unit>件|番目)?")
PACE_WORDS = ["語%d" % (i * 7919 % 5000) for i in range(30000)]


class PaceRow(tuple):
    __slots__ = ()
    start = property(lambda self: self[1])


PACE_ROWS = [PaceRow((i, i * 5, i * 5 + 5)) for i in range(1000)]


def pace():
    total = len(difflib.SequenceMatcher(None, PACE_OLD, PACE_NEW, autojunk=False).get_opcodes())
    for _ in range(6):
        counts = Counter()
        for sentence in PACE_SENTENCE.finditer(PACE_TEXT):
            for number in PACE_NUMBER.finditer(sentence.group()):
                counts[(number.group(), number.group("unit"))] += 1
        total += len(counts)
    for k in range(1000):
        total += next(row for row in PACE_ROWS if row.start <= k * 5 + 2 < row[2])[0]
    for _ in range(6):
        seen = {}
        for i, word in enumerate(PACE_WORDS):
            seen.setdefault(word, []).append(i)
        starts = sorted(len(places) * 100000 + k for k, places in enumerate(seen.values()))
        total += sum(bisect_left(starts, x) for x in range(0, 30000, 3))
    return total


def _pace():
    """(PACE_SECONDS, pace)。試験で差し替えられるよう、関数を通して渡す。"""
    return PACE_SECONDS, pace


def pace_scale(rounds=3):
    """この機械の遅さの比。pace を rounds 回動かした最も速い時間を PACE_SECONDS で割った値で、1 より小さければ 1。"""
    seconds, run = _pace()
    clock = timing_clock()
    best = None
    for _ in range(rounds):
        started = clock()
        run()
        elapsed = clock() - started
        best = elapsed if best is None else min(best, elapsed)
    return max(1.0, best / seconds)


def paced_limit(limit, elapsed):
    """(上限, 説明の文) を返す。POSIX と、elapsed が limit 未満のときは、上限は limit のまま（pace は測らない）。Windows で
    limit 以上なら pace を測り、limit をこの機械の遅さの比で延ばした値を上限にする。比は1以上なので、速い機械で上限が縮む
    ことはなく、実装が遅くなったときは、遅い機械でも、その遅さを除いた分だけ上限を超える。"""
    scale = 1.0 if sys.platform != "win32" or elapsed < limit else pace_scale()
    detail = "%.3f秒。上限 %.3f秒（%s秒 × この機械の遅さ %.2f）" % (elapsed, limit * scale, limit, scale)
    return limit * scale, detail


def files_folder(*paths):
    """3.0.0: lint は、作業フォルダの外のファイルを読まない。試験で一時フォルダのファイルをコマンドに渡すときは、
    そのファイルのあるフォルダで子を動かす。渡したパスのフォルダに共通する、いちばん深いフォルダの本当の場所を返す。"""
    import os
    return os.path.commonpath([os.path.dirname(os.path.realpath(str(path))) for path in paths])


class working_folder(object):
    """3.0.0: lint をプロセスの中で動かす試験で、渡すファイルのあるフォルダを作業フォルダにする（with の間だけ。
    終わると元の作業フォルダに戻す。一時フォルダを消す前に戻るよう、with では一時フォルダのあとに書く）。"""

    def __init__(self, path):
        self.path = str(path)
        self.previous = None

    def __enter__(self):
        import os
        self.previous = os.getcwd()
        os.chdir(self.path)
        return self.path

    def __exit__(self, *exc):
        import os
        os.chdir(self.previous)
        return False
