import argparse
from .study import evaluate

if __name__=='__main__':
    p=argparse.ArgumentParser(description='Execute only the frozen local mechanism probe; no model API.')
    p.add_argument('--output',required=True)
    a=p.parse_args();evaluate(a.output)
