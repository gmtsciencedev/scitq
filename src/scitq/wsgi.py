import sys
from pathlib import Path
import logging

executable = Path(sys.executable).resolve()

from gevent import monkey
monkey.patch_all()

from scitq.server import main,app

main()

