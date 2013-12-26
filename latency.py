#! /usr/bin/env python
# coding=utf-8
__author__ = 'jjay'
import argparse
import errno
import random
import re
import time
import weakref


import gevent
import gevent.server
import gevent.event

class GameError(RuntimeError):
    def __init__(self, loser):
        self.looser = loser
        super(GameError, self).__init__()

class BreakawayError(GameError):
    pass

class ClientDisconnected(GameError):
    pass


class Client(object):
    '''
    Client class.
    Handles user packets and sends exception-like signals to
    controller when events occurs (space symbol received or
    got disconnected)
    '''


    # search state - ignore any input from client
    SEARCH = 0
    # '1-2-3' state - treat space symbol as loose
    PREPARE = 1
    # 'after-3' state - first space recieved is a winner
    READY = 2


    # platform based telnet clients uses different linebreaks
    br = re.compile(r'\r\n|\n|\r', re.MULTILINE)

    def __init__(self, server, sock):
        self.sock = sock
        self.state = self.SEARCH
        self.buff = ''
        self.connected = True
        self.serve_task = None
        self.created_at = time.time()

        '''
        link to Controller needed to send win or disconnect events
        '''
        self.controller = None

        '''
        link to Server needed to cleanup its 'waiting_clients' after
        opponent got found and Controller created
        '''
        self.server = weakref.proxy(server)

    def greet(self):
        '''
        Send greet message to client
        '''
        self.send(u"Привет! Попробую найти тебе противника")

    def is_ready_for_game(self):
        return (self.server.time - self.created_at) > 1

    def found(self, controller):
        '''
        Set inner state to PREPARE
        Notify user about opponent is found
        '''
        self.state = self.PREPARE
        self.controller = weakref.proxy(controller)
        self.send(u"Противник найден. Нажмите пробел, когда увидите цифру 3")

    def go(self):
        self.state = self.READY

    def send(self, msg):
        self.sock.send("{0}\n".format(msg.encode('utf8')))

    def read(self):
        '''
        Read single message from stream and return it.
        Returns message or None if client have been disconnected.
        '''
        if self.buff:
            try:
                data, self.buff = self.br.split(self.buff, 1)
                return data
            except ValueError:
                # Buffer not fill
                pass

        try:
            # in most cases 8-byte buffer is enougth
            # as we awaiting only 1-symbol message
            read = self.sock.recv(8)
        except IOError as e:
            # Descriptor was closed in another greenlet by close()
            if e.errno == errno.EBADF:
                return None

        # Connection reset by client
        if not read:
            if self.controller:
                self.controller.game.kill(ClientDisconnected(self))
            self.disconnect()

        self.buff += read
        return self.read()

    def disconnect(self):
        if not self.connected:
            return
        self.connected = False

        if self.state == self.SEARCH:
            self.server.waiting_clients.remove(self)

        if self.server.custom_messages:
            self.send(u"Пока!")
        self.sock.close()

    def serve(self):
        self.serve_task = gevent.spawn(self._serve)

    def _serve(self):
        '''
        Serve task.
        Reads input from client.
        Sends events to controller based on inner state
        '''
        while self.connected:
            msg = self.read()

            # connection was closed, stop serve task
            if msg is None:
                break

            # not interested in receiving messages
            # while server search for opponent
            if self.state == self.SEARCH:
                continue

            # only ' ' is valid symbol for win/lose conditions
            if msg != ' ':
                if self.server.custom_messages:
                    self.send(u"Я понимаю только пробельный символ (' ')")
                continue


            # ups, recv too early, loose
            if self.state == self.PREPARE:
                self.controller.game.kill(BreakawayError(self))
                break

            # possible win
            # controller can be missed at this step
            if self.state == self.READY:
                if not (self.controller is None):
                    self.controller.winner.set(self)
                break


class Controller(object):
    '''
    Controller represents game room.
    It holds links to clients and handle game logic -
    sends 1-2-3 messages, waits for first space simbols,
    sends win-lose messages.
    '''
    def __init__(self, server, client1, client2):
        self.clients = [client1, client2]

        '''
        Client sets this result (Client object) from client serve loop.
        First client stored result will awake controller and
        Controller treats it as winner.
        '''
        self.winner = gevent.event.AsyncResult()

        '''
        Game process greenlet. Needed to send exceptions to it -
        when client send space symbol too early or when client
        disconnects while game in progress.
        '''
        self.game = None

        '''
        Link to server instance needed to be able to clean server
        from controller itself after game finishes.
        '''
        self.server = weakref.proxy(server)

    def send(self, msg):
        '''
        Sends message to each client
        '''
        [c.send(msg) for c in self.clients]

    def go(self):
        '''
        After this call, first client received '3' will be
        treated as winner
        '''
        [c.go() for c in self.clients]

    def win(self, winner):
        '''
        Notify clients for win event -
        nobody have sent space symbol too early, but
        one client was faster and wins.
        '''
        loser = [c for c in self.clients if c!= winner][0]
        winner.send(u"Вы нажали пробел первым и победили")
        loser.send(u"Вы не успели и проиграли")
        gevent.sleep(0.5)

    def lose(self, loser):
        '''
        Notify clients for lose event -
        someone have sent space symbol too early, before
        '3', or got disconnected.
        '''
        winner = [c for c in self.clients if c != loser][0]
        winner.send(u"Ваш противник поспешил и вы выиграли")
        loser.send(u"Вы поспешили и проиграли")
        gevent.sleep(0.5)

    def disconnect(self):
        '''
        Disconnect both clients and cleanup itself from server
        '''
        self.server.games.discard(self)
        [c.disconnect() for c in self.clients]

    def play(self):
        '''
        Set Client state into 'Game found' and
        runs game greenlet
        '''
        [c.found(self) for c in self.clients]
        self.game = gevent.spawn(self._play)

    def withdraw(self):
        '''
        Notify clients for withdraw event (if server run
        with --timeout flag)
        '''
        self.send(u"Я устал вас ждать. Ничья.")
        gevent.sleep(0.5)

    def _play(self):
        '''
        Main game process
        '''
        try:
            delays = [(unicode(i+1), 2 + random.random()*2) for i in range(3)]
            for step, delay in delays:
                gevent.sleep(delay)
                self.send(step)
            self.go()
            # Client sets this result when recv space symbol
            winner = self.winner.get(timeout=self.server.timeout)
            self.win(winner)

        # Client sends this exception if disconnected
        except BreakawayError as e:
            self.lose(e.looser)

        # Client sends whis exception if recv space symbol before
        # '3' is received
        except ClientDisconnected as e:
            self.lose(e.looser)


        # Timeout occures while waiting self.winner.get
        except gevent.Timeout:
            self.withdraw()
        finally:
            self.disconnect()



class Server(object):
    '''
    Server holds links to Controllers and Clients waiting for games.
    Organise matchups each second.
    '''
    def __init__(self, listen, custom_messages=False, timeout=None):
        print "Starting server on {0}".format(listen)
        # for backwards compatibity with gevent<=1.0
        listen = listen.split(':')
        listen[1] = int(listen[1])
        listen = tuple(listen)

        self.impl = gevent.server.StreamServer(listen, self.handle)
        self.games = set()
        self.waiting_clients = []
        self.time = time.time
        self.custom_messages = custom_messages
        self.timeout = timeout


    def start(self):
        gevent.spawn(self.matchup)
        self.impl.serve_forever()

    def matchup(self):
        '''
        Matchup task.
        Use simple algorithm - just join to nearest by connection time clients.
        '''
        while True:
            gevent.sleep(1)
            self.time = time.time()

            while len(self.waiting_clients) > 1:
                if not self.waiting_clients[1].is_ready_for_game():
                    break

                controller = Controller(self, *self.waiting_clients[:2])
                self.waiting_clients = self.waiting_clients[2:]
                self.games.add(controller)
                controller.play()

    def handle(self, socket, addr):
        client = Client(self, socket)
        client.greet()
        client.serve()
        self.waiting_clients.append(client)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("address", nargs='?', type=str, default='localhost:31337', help="Address to listen. Default to localhost:31337")
    parser.add_argument("--timeout", type=float, default=None, help="Game timeout in seconds. By default each game run with no timeout")
    parser.add_argument("--custom-messages", action='store_true', help="Use custom messages, not specified in task.")
    args = parser.parse_args()

    server = Server(args.address, timeout=args.timeout, custom_messages=args.custom_messages)
    server.start()
