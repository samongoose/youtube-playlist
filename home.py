import tornado.web
import tornado.options
import tornado.ioloop
import tornado.httpserver
import redis
import json
import os
import tornado.websocket
import threading

from datetime import timedelta

from tornado.httpserver import HTTPServer
from tornado.web import Application
from tornado.websocket import WebSocketHandler
from tornado.web import RequestHandler
from utils import playlist_key, tags_key, tag_key, playlist_name_key, names_key
from tornado.web import addslash

_redis_client = redis.StrictRedis(host='localhost', port=6379, db=0)

def publish_change(key, item_type, action):
    publish_info = {
        'action':action,
        'type':item_type
    }
    _redis_client.publish(key, json.dumps(publish_info))



class PlaylistController(RequestHandler):
    
    @addslash
    def get(self, playlist):
        if len(playlist) <= 0:
            #TODO:404
            return self.write("")
        playlist_json = {}
        playlist_json['items'] = list(json.loads(s)
              for s in _redis_client.lrange(playlist_key(playlist), 0, -1))
        playlist_json['tags'] = _redis_client.zrange(tags_key(playlist), 0, -1)
        name = _redis_client.get(playlist_name_key(playlist))
        if name is not None:
            playlist_json['name'] = name
        return self.render("playlist_view.html", 
                  pid=playlist,
                  name=name, 
                  playlist =json.dumps(playlist_json))

  
    def put(self, playlist):
        if len(playlist) <= 0:
            #404?
            return self.write("")
        name = self.get_argument('name', None)
        if name is not None:
            old_name = _redis_client.getset(playlist_name_key(playlist), name)
            if old_name is not None:
                _redis_client.lrem(names_key(old_name), 0, old_name)
            _redis_client.rpush(names_key(name), playlist)


class PlaylistsController(RequestHandler):
    def post(self):
        #create new playlist
        playlist = _redis_client.incr("global:nextPlaylistId")
        playlist_name = 'Playlist ' + str(playlist)
        _redis_client.set(playlist_name_key(playlist), playlist_name)
        _redis_client.rpush(names_key(playlist_name), playlist)
        self.set_header('Location', '/Playlists/' + str(playlist) + '/')
        self.set_status(201)
        return ""

    @staticmethod
    def get_playlist_data(pid):
        name = _redis_client.get(playlist_name_key(pid))
        if name is None:
            name = "Untitled"
        return { 'id':pid, 'name':name}

    def get(self):
        results = []
        tag = self.get_argument('tag', None)
        if tag is not None:
            results = _redis_client.smembers(tag_key(tag))
            
        playlist_data = list(
              PlaylistsController.get_playlist_data(p) for p in results)
         
        return self.write(json.dumps(playlist_data))


class TagsController(RequestHandler):
    def post(self, playlist):
        new_tag = self.request.body
        if len(new_tag) <= 0:
            return self.write("")
        next_tag = _redis_client.incr('playlists:%s:next_tagID' % playlist)
        added = _redis_client.zadd(
              tags_key(playlist), next_tag, new_tag) == True

        if not added:
            print "Failure"
            return self.write("")
        
        _redis_client.sadd(tag_key(new_tag), playlist)
        self.set_status(201)
        publish_change(playlist_key(playlist), 'tag', 'add')
        return self.write("")

    @addslash
    def get(self, playlist):
        tags_json = json.dumps(_redis_client.zrange(tags_key(playlist), 0, -1))
        return self.write(tags_json)

class TagController(RequestHandler):
    def delete(self, playlist, tag):
        if len(tag) <= 0:
            #TODO:404
            return self.write("")
        _redis_client.zrem(tags_key(playlist), tag)
        _redis_client.srem(tag_key(tag), playlist)
        publish_change(playlist_key(playlist), 'tag', 'delete')
        self.set_status(204)
        self.write("")

class ItemsController(RequestHandler):
    def post(self, playlist):
        new_item = self.request.body
        if len(new_item) <= 0:
            return self.write("")
        list_length = _redis_client.rpush('playlists:' + playlist, new_item)
        publish_change(playlist_key(playlist), 'item', 'add')
        self.set_header('Location', '/Playlists/%s/Items/%s/' % 
                       (playlist, list_length))
        self.set_status(201)
        return self.write("")


    @addslash
    def get(self, playlist):
        #TODO:Query here...
        playlist_json = json.dumps(
              list(json.loads(s) 
              for s in _redis_client.lrange(playlist_key(playlist), 0, -1)))
        return self.write(playlist_json)

class ItemController(RequestHandler):

    @addslash
    def get(self, playlist, item):
        return self.write(str(
           _redis_client.lindex("playlists:" + playlist, int(item))))

    def delete(self, playlist, item):
        if len(item) <= 0:
            print "error"
            return self.write("")

        index = int(item)
        if index < _redis_client.llen(playlist_key(playlist)):
            _redis_client.lset(playlist_key(playlist), item, "TO_DELETE")
            _redis_client.lrem(playlist_key(playlist), 0, "TO_DELETE")
            publish_change(playlist_key(playlist), 'item', 'delete')
        self.set_status(204)
        return self.write("")

class Index(RequestHandler):
    @addslash
    def get(self):
        return self.render("index.html")


class SocketHandler(WebSocketHandler):

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
                        self._socket.write_message(item['data'])

    def __init__(self, *args, **kwargs):
        WebSocketHandler.__init__(self, *args, **kwargs)
        self._client = None
        self._channel = None
        self._listener = None

    def _listen(self, channel):
        self._client = _redis_client.pubsub()
        self._channel = channel
        self._client.subscribe(self._channel)
        self._listener = self.ListenerThread(self._client, self)
        self._listener.setDaemon(True)
        self._listener.start()

    def on_message(self, msg):
        if msg.kind == 'message':
            self.write_message(msg.body)

    def open(self, playlist):
        self._listen(playlist_key(playlist))

    def on_close(self):
        if self._listener is not None:
            self._listener.end_thread_event.set()
            self._client.unsubscribe(self._channel)
        print "closed"

_settings = {
    "static_path": os.path.join(os.path.dirname(__file__), "static"),
    "template_path": os.path.join(os.path.dirname(__file__), "templates"),
}


_application = Application ([
    (r"/Playlists/([^/]+)/Items/([^/]+)/?", ItemController),
    (r"/Playlists/([^/]+)/Items/?", ItemsController),
    (r"/Playlists/([^/]+)/Tags/([^/]+)/?", TagController),
    (r"/Playlists/([^/]+)/Tags/?", TagsController),
    (r"/Playlists/([^/]+)/?", PlaylistController),
    (r"/Playlists/?", PlaylistsController),
    (r"/", Index)
], **_settings)

def set_ping(io_loop, timeout):
    io_loop.add_timeout(timeout, lambda: set_ping(io_loop, timeout))

if __name__ == "__main__":
    _application.listen(8888)
    HTTPServer(Application(
               [(r'/Playlists/(.*)/', SocketHandler)])).listen(7657)
    _ioloop = tornado.ioloop.IOLoop.instance()
    set_ping(_ioloop, timedelta(seconds=2))
    _ioloop.start()
