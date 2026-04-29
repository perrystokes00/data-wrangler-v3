"""
write_dist_env.py  —  Writes .env to dist folder during build.
Called by build_dist.bat.
Usage: python write_dist_env.py <src_dir> <dest_dir>
"""
import os
import sys
import pathlib

sys.path.insert(0, sys.argv[1])  # add src to path so dotenv finds .env
from dotenv import load_dotenv

src  = pathlib.Path(sys.argv[1])
dest = pathlib.Path(sys.argv[2])

load_dotenv(src / ".env")

token  = os.getenv("LICENCE_GITHUB_TOKEN", "")
repo   = os.getenv("LICENCE_GITHUB_REPO",  "perrystokes00/dw_licences")
secret = os.getenv("LICENCE_SECRET", "")

content = "\n".join([
    "# Data Wrangler configuration",
    "# Do not share this file",
    "",
    "# Anthropic API key - required for AI Assistant",
    "# Get yours at: https://console.anthropic.com",
    "ANTHROPIC_API_KEY=",
    "",
    "# Licence validation - provided by Data Wrangler team",
    f"LICENCE_GITHUB_TOKEN={token}",
    f"LICENCE_GITHUB_REPO={repo}",
    f"LICENCE_SECRET={secret}",
])

(dest / ".env").write_text(content)
print(f"  .env written with token and secret.")
