"""Interactive local launcher; no secrets in command history or saved config."""
import getpass
import os
from pathlib import Path
import subprocess

if __name__ == '__main__':
    print('AEGIS chart reader. Reads your open chart; never places trades.')
    env = dict(os.environ)
    env['TRADINGVIEW_MCP_DIR'] = str(Path(input('TradingView MCP folder: ').strip()).expanduser().resolve())
    env['AEGIS_CHART_TOKEN'] = getpass.getpass('AEGIS chart token (hidden): ')
    bypass = getpass.getpass('Existing Vercel automation credential if required (hidden, or Enter): ')
    if bypass:
        env['VERCEL_AUTOMATION_BYPASS_SECRET'] = bypass
    env['AEGIS_VISION'] = '1' if input('Enable paid image analysis at most once / 5 minutes? [y/N] ').lower()=='y' else '0'
    subprocess.run(['node',str(Path(__file__).with_name('collector.mjs'))],env=env,check=True)
