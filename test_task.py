# coding=utf-8
import random
import re

__author__ = 'jjay'

import errno

import gevent
import gevent.socket


class Client(object):
    br = re.compile(r'\r\n|\n|\r', re.MULTILINE)
    numclients = 0
    def __init__(self):
        self.sock = gevent.socket.create_connection(('localhost', 31337))
        self.buff = ''
        self.num = Client.numclients
        Client.numclients += 1

    def send(self, msg):
        self.sock.send("{0}\n".format(msg.encode('utf8')))

    def recv(self):
        if self.buff:
            try:
                data, self.buff = self.br.split(self.buff, 1)
                data = data.decode('utf8')
                return data
            except ValueError:
                # Buffer not fill
                pass

        try:
            read = self.sock.recv(1024)
        except IOError as e:
            # Descriptor was closed in another greenlet by close()
            if e.errno == errno.EBADF:
                return None

        if not read:
            self.sock.close()
            return None

        self.buff += read
        return self.recv()


TESTS = 0
WINS = 0
LOSE = 0

def test():
    global TESTS, WINS, LOSE
    TESTS += 1
    client = Client()
    data = client.recv()
    assert data == u"Привет! Попробую найти тебе противника"

    data = client.recv()
    assert data == u"Противник найден. Нажмите пробел, когда увидите цифру 3"

    data = client.recv()
    assert data == u"1"
    data = client.recv()
    assert data == u"2"
    data = client.recv()
    assert data == u"3"
    gevent.sleep(random.random())

    client.send(u' ')

    data = client.recv()
    if data == u"Вы нажали пробел первым и победили":
        WINS += 1
    elif data == u"Вы не успели и проиграли":
        LOSE += 1
    else:
        raise RuntimeError("Unexcepted content from server: {0}".format(repr(data)))


tasks = [gevent.spawn(test) for i in range(4096)]
gevent.joinall(tasks)

print "Test runs:", TESTS
print "Test wins:", WINS
print "Test loses:", LOSE
print "Test errors", (TESTS - WINS - LOSE)