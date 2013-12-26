REQUIREMENTS
============

`python-gevent` package required for running server.

Under Ubuntu:
```bash
apt-get install python-gevent`
```

Under Ubuntu using virtualenv:
```bash
sudo apt-get install python-virtualenv python-dev libev-dev
cd /path/to/latency/
virtualenv .env
source .env/bin/activate
pip install gevent
```

Under MacOs using virtualenv:
```bash
brew install libev python
cd /path/to/latency/
virtualenv .env
source .env/bin/activate
pip install gevent
```


USAGE
=====

`./latency.py`

or

`./latency.py --help` for help
