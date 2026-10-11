import os
from render_turn import render
render()
os.execvp('turnserver', ['turnserver', '-c', '/tmp/turnserver.conf'])
