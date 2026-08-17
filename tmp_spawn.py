import subprocess, sys, os

venv = r"C:\Users\Paterne BALAGIZI\Documents\Codex\2026-07-20\cr-e-une-t-che-programm\.venv\Scripts\python.exe"
wd = r"C:\Users\Paterne BALAGIZI\Documents\Codex\2026-07-20\cr-e-une-t-che-programm"
out = os.path.join(wd, "llm2_out.txt")
err = os.path.join(wd, "llm2_err.txt")
with open(out, "w") as fo, open(err, "w") as fe:
    p = subprocess.Popen(
        [venv, "-X", "utf8", "tmp_test_llm2.py"],
        cwd=wd, stdout=fo, stderr=fe,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
    )
print("PID:", p.pid)