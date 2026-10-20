#!/usr/bin/env python3
"""Set the advisory Neat extension countdown in a local SDK container."""
import argparse
import datetime
import json
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('container', help='SDK Docker container name')
action = parser.add_mutually_exclusive_group()
action.add_argument('--minutes', type=int, help='Minutes remaining (0 displays expired)')
action.add_argument('--expires-at', help='Exact ISO expiration including timezone, e.g. 2026-10-21T18:00:00-07:00')
parser.add_argument('--display', choices=['auto', 'quiet', 'warning', 'urgent'], help='Presentation mode; may be updated without changing the deadline')
action.add_argument('--clear', action='store_true', help='Hide the countdown')
blink = parser.add_mutually_exclusive_group()
blink.add_argument('--blink', dest='blink', action='store_true', default=None, help='Blink the footer highlight once every two seconds')
blink.add_argument('--no-blink', dest='blink', action='store_false', help='Keep the footer highlight steady')
parser.add_argument('--blink-color', choices=['red', 'amber'], help='Blink background color (default red); does not enable blinking by itself')
args = parser.parse_args()
if args.minutes is not None and not 0 <= args.minutes <= 525600:
    parser.error('--minutes must be between 0 and 525600')
if args.clear and (args.display or args.blink is not None or args.blink_color):
    parser.error('--clear cannot be combined with display or blink options')
if not args.clear and args.minutes is None and not args.expires_at and not args.display and args.blink is None and not args.blink_color:
    parser.error('Specify --expires-at, --minutes, --display, --blink, --no-blink, --blink-color, or --clear')
update = {}
if args.clear:
    update['expiresAt'] = None
elif args.expires_at:
    try:
        deadline = datetime.datetime.fromisoformat(args.expires_at.replace('Z', '+00:00'))
        if deadline.tzinfo is None:
            raise ValueError('Timezone is required')
    except ValueError as error:
        parser.error(f'Invalid --expires-at: {error}')
    update['expiresAt'] = deadline.isoformat()
elif args.minutes is not None:
    update['expiresAt'] = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=args.minutes)).isoformat()
if args.display:
    update['display'] = args.display
if args.blink is not None:
    update['blink'] = args.blink
if args.blink_color:
    update['blinkColor'] = args.blink_color
payload = json.dumps(update)
# Rename within the same directory so readers never see partial JSON.
writer = '''
import json, os, sys, tempfile
folder = '/run/sima-neat'
os.makedirs(folder, mode=0o755, exist_ok=True)
update = json.loads(sys.argv[1])
if 'expiresAt' not in update:
    try:
        with open(folder + '/session.json') as source:
            previous = json.load(source)
    except FileNotFoundError:
        previous = {}
    except (OSError, ValueError) as error:
        raise SystemExit(f'Cannot read current session state: {error}. Set --expires-at or --minutes to replace it.')
    if not isinstance(previous, dict) or not previous.get('expiresAt'):
        raise SystemExit('No expiration is configured. Add --minutes 30 or --expires-at <ISO timestamp> to this command.')
    update = {**previous, **update}
fd, temporary = tempfile.mkstemp(prefix='.session-', dir=folder)
try:
    with os.fdopen(fd, 'w') as out:
        out.write(json.dumps(update) + '\\n')
        os.fchmod(out.fileno(), 0o644)
    os.replace(temporary, folder + '/session.json')
finally:
    if os.path.exists(temporary): os.unlink(temporary)
'''
try:
    subprocess.run(['docker', 'exec', '--workdir', '/', '--user', '0', args.container, 'python3', '-c', writer, payload], check=True)
except subprocess.CalledProcessError as error:
    # Docker/the writer already printed the diagnostic; do not dump its command.
    sys.exit(error.returncode if error.returncode > 0 else 1)
except OSError as error:
    sys.exit(f'Unable to run Docker: {error}')
print('Countdown hidden.' if args.clear else 'Session control updated: ' + payload)
