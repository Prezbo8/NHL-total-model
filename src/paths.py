"""Where things live: data files in data/, the website in docs/ (paths work from any working directory)."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
DOCS_DIR = os.path.join(ROOT, "docs")


def data(name):
    return os.path.join(DATA_DIR, name)
