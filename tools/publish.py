"""公開用の履歴(ブランチ public)に、いまの main の中身を1つのコミットとして積む。

手元の main の履歴には、作者さんの資料(実装表の PDF)が入っているので、そのまま公開しない。
public は main とつながっていない別の履歴で、EXCLUDE を除いた中身だけを持つ。
GitHub には public を main として送る:  git push origin public:main

    python tools/publish.py "メッセージ" --author "名前 <メール>"

中身が前回の public と同じなら何もしない。main の作業ツリーやブランチには触らない。
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE = ["docs/Famimimidi_implement_chart_v10.pdf"]     # 作者さんの資料。公開しない
BRANCH = "public"


def git(*args, env=None, check=True):
    r = subprocess.run(["git", *args], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        sys.exit(f"git {' '.join(args)} が失敗しました:\n{r.stderr}")
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("message")
    ap.add_argument("--author", required=True, help='"名前 <メール>"(公開用。GitHub の noreply アドレスがおすすめ)')
    ap.add_argument("--source", default="main")
    a = ap.parse_args()
    name, _, mail = a.author.partition("<")
    name, mail = name.strip(), mail.strip(" >")
    if not name or not mail:
        sys.exit('--author は "名前 <メール>" の形で指定してください')

    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(tmp) / "index"))
        git("read-tree", a.source, env=env)
        for path in EXCLUDE:
            git("rm", "--cached", "--quiet", "--ignore-unmatch", path, env=env)
        tree = git("write-tree", env=env)

    listed = git("ls-tree", "-r", "--name-only", tree)
    leaked = [p for p in EXCLUDE if p in listed.splitlines()]
    if leaked:
        sys.exit(f"除外できていません: {leaked}")

    parent = git("rev-parse", "--verify", "--quiet", BRANCH, check=False)
    if parent and git("rev-parse", f"{parent}^{{tree}}") == tree:
        print("前回の public と中身が同じなので、何もしません。")
        return
    env = dict(os.environ, GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=mail, GIT_COMMITTER_NAME=name, GIT_COMMITTER_EMAIL=mail)
    args = ["commit-tree", tree, "-m", a.message] + (["-p", parent] if parent else [])
    commit = git(*args, env=env)
    git("update-ref", f"refs/heads/{BRANCH}", commit)
    print(f"{BRANCH} を更新しました: {commit[:7]}({len(listed.splitlines())} ファイル)")
    print("GitHub に送るには:  git push origin public:main")


if __name__ == "__main__":
    main()
