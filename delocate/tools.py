import sys

if sys.platform == 'win32':
    from .win32.tools import * 
else:
    from .osx.tools import *