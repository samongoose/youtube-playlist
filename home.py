import tornado.web
import tornado.options
import tornado.ioloop
import tornado.httpserver
import json
import tornado.websocket
import threading
import tornadio2

from datetime import timedelta
from tornado import httpclient
from tornado.httpserver import HTTPServer
from tornado.web import Application
from tornado.websocket import WebSocketHandler
from tornado.web import RequestHandler
from utils import *
from tornado.web import addslash
from tornadio2 import SocketConnection, TornadioRouter, SocketServer, event



class PlaylistController(RequestHandler):
    
    @addslash
    def get(self, playlist):
        if len(playlist) <= 0:
            raise httpcilent.HTTPError(404)

        playlist_json = {}
        playlist_json['items'] = list(json.loads(s)
              for s in redis_client.lrange(playlist_key(playlist), 0, -1))
        playlist_json['tags'] = redis_client.zrange(tags_key(playlist), 0, -1)
        name = redis_client.get(playlist_name_key(playlist))
        if name is not None:
            playlist_json['name'] = name
        if self.get_argument('fmt', 'html') == 'json':
            self.set_header('Content-Type', 'application/json')
            return self.write(json.dumps(playlist_json))
        else:
            return self.render('playlist_view.html', 
                  pid=playlist,
                  name=name, 
                  playlist =json.dumps(playlist_json))

    def put(self, playlist):
        if len(playlist) <= 0:
            raise httpcilent.HTTPError(404)
        name = self.get_argument('name', None)
        if name is not None:
            old_name = redis_client.getset(playlist_name_key(playlist), name)
            if old_name is not None:
                redis_client.lrem(names_key(old_name), 0, old_name)
            redis_client.rpush(names_key(name), playlist)


class PlaylistsController(RequestHandler):
    def post(self):
        #create new playlist
        playlist = redis_client.incr('global:nextPlaylistId')
        playlist_name = 'Playlist {}'.format(playlist)
        redis_client.set(playlist_name_key(playlist), playlist_name)
        redis_client.rpush(names_key(playlist_name), playlist)
        self.set_header('Location', '/Playlists/{}/'.format(str(playlist)))
        self.set_status(201)
        return ''

    @staticmethod
    def get_playlist_data(pid):
        name = redis_client.get(playlist_name_key(pid))
        if name is None:
            name = 'Untitled'
        return { 'id':pid, 'name':name}

    def get(self):
        results = []
        tag = self.get_argument('tag', None)
        if tag is not None:
            results = redis_client.smembers(tag_key(tag))
            
        playlist_data = list(
              PlaylistsController.get_playlist_data(p) for p in results)
         
        self.set_header('Content-Type', 'application/json')
        return self.write(json.dumps(playlist_data))


class TagsController(RequestHandler):
    def post(self, playlist):
        new_tag = self.request.body
        if len(new_tag) <= 0:
            return self.write('')
        next_tag = redis_client.incr('playlists:{}:next_tagID'.format(playlist))
        added = redis_client.zadd(
              tags_key(playlist), new_tag, next_tag) == True

        if not added:
            print 'Failure'
            return self.write('')
        
        redis_client.sadd(tag_key(new_tag), playlist)
        self.set_status(201)
        publish_change(playlist_key(playlist), 'tag', 'add')
        return self.write('')

    @addslash
    def get(self, playlist):
        tags_json = json.dumps(redis_client.zrange(tags_key(playlist), 0, -1))
        self.set_header('Content-Type', 'application/json')
        return self.write(tags_json)

class TagController(RequestHandler):
    def delete(self, playlist, tag):
        if len(tag) <= 0:
            raise httpcilent.HTTPError(404)

        redis_client.zrem(tags_key(playlist), tag)
        redis_client.srem(tag_key(tag), playlist)
        publish_change(playlist_key(playlist), 'tag', 'delete')
        self.set_status(204)
        self.write('')

class ItemsController(RequestHandler):
    def post(self, playlist):
        new_item = self.request.body
        if len(new_item) <= 0:
            return self.write('')
        list_length = redis_client.rpush('playlists:{}'.format(playlist), new_item)
        publish_change(playlist_key(playlist), 'item', 'add')
        self.set_header('Location', '/Playlists/{}/Items/{}/'.format( 
                       playlist, list_length))
        self.set_status(201)
        return self.write('')


    @addslash
    def get(self, playlist):
        #TODO:Query here...
        playlist_json = json.dumps(
              list(json.loads(s) 
              for s in redis_client.lrange(playlist_key(playlist), 0, -1)))
        self.set_header('Content-Type', 'application/json')
        return self.write(playlist_json)

class ItemController(RequestHandler):

    @addslash
    def get(self, playlist, item):
        return self.write(str(
           redis_client.lindex('playlists:{}'.format(playlist), int(item))))

    def delete(self, playlist, item):
        if len(item) <= 0:
            print 'error'
            return self.write('')

        index = int(item)
        if index < redis_client.llen(playlist_key(playlist)):
            redis_client.lset(playlist_key(playlist), item, 'TO_DELETE')
            redis_client.lrem(playlist_key(playlist), 'TO_DELETE')
            publish_change(playlist_key(playlist), 'item', 'delete')
        self.set_status(204)
        return self.write('')

class Index(RequestHandler):
    @addslash
    def get(self):
        return self.render('index.html')


class SocketIOHandler(tornado.web.RequestHandler):
    def get(self):
        self.render('static/js/socket.io.min.js')

class SocketHandler(tornadio2.conn.SocketConnection):

    class ListenerThread(threading.Thread):
        def __init__(self, client, socket):
            threading.Thread.__init__(self)
            self._socket = socket
            self._client = client
            self.end_thread_event = threading.Event()

        def run(self):
            while not self.end_thread_event.isSet():
                for item in self._client.listen():
                    if item['type'] == 'message':
                        self._socket.send(item['data'])

    def __init__(self, *args, **kwargs):
        tornadio2.conn.SocketConnection.__init__(self, *args, **kwargs)
        self._client = None
        self._channel = None
        self._listener = None

    def _listen(self, channel):
        self._client = redis_client.pubsub()
        self._channel = channel
        self._client.subscribe(self._channel)
        self._listener = self.ListenerThread(self._client, self)
        self._listener.setDaemon(True)
        self._listener.start()

    def on_message(self, msg):
        if msg.kind == 'message':
            self.send(msg.body)

    def on_open(self, request):
        print 'Connecting'
        self._listen(playlist_key(request.get_argument('playlistid')))

    def on_close(self):
        if self._listener is not None:
            self._listener.end_thread_event.set()
            self._client.unsubscribe(self._channel)
        print 'closed'

_settings = {
    'static_path': os.path.join(os.path.dirname(__file__), 'static'),
    'template_path': os.path.join(os.path.dirname(__file__), 'templates'),
}

ROOT = op.normpath(op.dirname(__file__))

_ws_router = tornadio2.router.TornadioRouter(SocketHandler, 
        user_settings=dict(enabled_protocols=['xhr-polling']))
_application = tornado.web.Application(
    _ws_router.apply_routes([(r'/socket.io.js', SocketHandler),
        (r'/Playlists/([^/]+)/Items/([^/]+)/?', ItemController),
        (r'/Playlists/([^/]+)/Items/?', ItemsController),
        (r'/Playlists/([^/]+)/Tags/([^/]+)/?', TagController),
        (r'/Playlists/([^/]+)/Tags/?', TagsController),
        (r'/Playlists/([^/]+)/?', PlaylistController),
        (r'/Playlists/?', PlaylistsController),
        (r'/', Index)]),
    flash_policy_port = os.environ.get('PORT',843),
    flash_policy_file = op.join(ROOT, 'flashpolicy.xml'),
    socket_io_port = os.environ.get('PORT', 8888),
    **_settings)

def set_ping(io_loop, timeout):
    io_loop.add_timeout(timeout, lambda: set_ping(io_loop, timeout))

if __name__ == '__main__':
    tornadio2.server.SocketServer(_application, xheaders=True, auto_start=False)

    _ioloop = tornado.ioloop.IOLoop.instance()
    set_ping(_ioloop, timedelta(seconds=2))
    _ioloop.start()
