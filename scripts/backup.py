"""Create, verify or restore a private SnapSell recovery archive."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'snapsell-backend'))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1]/'.env')
import backups

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify',type=Path)
    parser.add_argument('--restore',type=Path)
    parser.add_argument('--to',type=Path)
    args=parser.parse_args()
    if args.verify:
        result=backups.verify(args.verify);print('Verified',len(result['files']),'files.')
    elif args.restore:
        if not args.to:parser.error('--restore requires --to NEW_DIRECTORY')
        print('Restored:',backups.restore(args.restore,args.to))
    else:print('Private backup created:',backups.create())
