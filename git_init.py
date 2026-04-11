import subprocess, sys

root = "/home/sean-campbell/github/willow-1.7"

cmds = [
    ["git", "-C", root, "init"],
    ["git", "-C", root, "config", "user.name", "Sean Campbell"],
    ["git", "-C", root, "config", "user.email", "sean@utety.com"],
    ["git", "-C", root, "add", "."],
    ["git", "-C", root, "commit", "-m", "Willow 1.7 initial - PGP-hardened SAP gate"],
]

for cmd in cmds:
    r = subprocess.run(cmd, capture_output=True, text=True)
    label = " ".join(cmd[2:])
    print(f"[{label}] rc={r.returncode}")
    if r.stdout.strip():
        print("  stdout:", r.stdout.strip())
    if r.stderr.strip():
        print("  stderr:", r.stderr.strip())
    if r.returncode != 0:
        sys.exit(r.returncode)

print("Done.")
