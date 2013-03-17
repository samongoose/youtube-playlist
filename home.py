import tornado.web
import tornado.options
import tornado.ioloop
import tornado.httpserver
import redis
import json
import os
import tornado.websocket
import utils
import threading

from datetime import timedelta

from tornado.options import options
from tornado.httpserver import HTTPServer
from tornado.web import Application
from tornado.websocket import WebSocketHandler
from tornado.web import RequestHandler
from utils import PlaylistKey, TagsKey, TagKey, PlaylistNameKey, NamesKey
from tornado.web import addslash

r = redis.StrictRedis(host='localhost', port=6379, db=0)

def PublishChange(key, itemType, action):
   publishInfo = {
      'action':action,
      'type':itemType
   }
   r.publish(key, json.dumps(publishInfo))



class PlaylistController(RequestHandler):
   
   @addslash
   def get(self, playlist):
      if len(playlist) <= 0:
         #TODO:404
         return self.write("")
      playlistJson = {}
      playlistJson['items'] = list(json.loads(s) for s in r.lrange(PlaylistKey(playlist), 0, -1))
      playlistJson['tags'] = r.zrange(TagsKey(playlist), 0, -1)
      name = r.get(PlaylistNameKey(playlist))
      if (name is not None):
         playlistJson['name'] = name
      return self.render("playlist_view.html", pid=playlist, name=name, playlist=json.dumps(playlistJson))

  
   def put(self, playlist):
      if (len(playlist) <= 0):
         #404?
         return self.write("")
      name = self.get_argument('name', None)
      if (name is not None):
         oldName = r.getset(PlaylistNameKey(playlist), name)
         if (oldName is not None):
            r.lrem(NamesKey(oldName), 0, oldName)
         r.rpush(NamesKey(name), playlist)


class PlaylistsController(RequestHandler):
   def post(self):
      #create new playlist
      playlist= r.incr("global:nextPlaylistId")
      playlistName = 'Playlist ' + str(playlist)
      r.set(PlaylistNameKey(playlist), playlistName)
      r.rpush(NamesKey(playlistName), playlist)
      self.set_header('Location', '/Playlists/' + str(playlist) + '/')
      self.set_status(201)
      return ""

   def get(self):
      results = []
      tag = self.get_argument('tag', None)
      if (tag is not None):
         results = r.smembers(TagKey(tag))
         
      def playlistGenerator(pid):
         name = r.get(PlaylistNameKey(pid))
         if (name is None):
            name = "Untitled";
         return { 'id':pid, 'name':name}

      retVal = list(playlistGenerator(p) for p in results)
       
      return self.write(json.dumps(retVal))


class TagsController(RequestHandler):
   def post(self, playlist):
      newTag = self.request.body
      if (len(newTag) <= 0):
         return self.write("")
      nextTag = r.incr('playlists:%s:nextTagID' % playlist)
      added = r.zadd(TagsKey(playlist), nextTag, newTag) == True
      if not added:
         print "Failure"
         return self.write("")
      
      r.sadd(TagKey(newTag), playlist)
      #self.set_header('Location', '/Playlists/%s/Tags/%s/' % (playlist, listLength))
      self.set_status(201)
      PublishChange(PlaylistKey(playlist), 'tag', 'add')
      return self.write("")

   @addslash
   def get(self, playlist):
      tagsJson = json.dumps(r.zrange(TagsKey(playlist), 0, -1))
      return self.write(tagsJson)

class TagController(RequestHandler):
   def delete(self, playlist, tag):
      if len(tag) <= 0:
         #TODO:404
         return self.write("")
      r.zrem(TagsKey(playlist), tag)
      r.srem(TagKey(tag), playlist)
      PublishChange(PlaylistKey(playlist), 'tag', 'delete')
      self.set_status(204)
      self.write("")

class ItemsController(RequestHandler):
   def post(self, playlist):
      newItem = self.request.body
      if (len(newItem) <= 0):
         return self.write("");
      listLength = r.rpush('playlists:' + playlist, newItem)
      PublishChange(PlaylistKey(playlist), 'item', 'add')
      self.set_header('Location', '/Playlists/%s/Items/%s/' % (playlist, listLength))
      self.set_status(201)
      return self.write("")


   @addslash
   def get(self, playlist):
      #TODO:Query here...
      playlistJson = json.dumps(list(json.loads(s) for s in r.lrange(PlaylistKey(playlist), 0, -1)))
      return self.write(playlistJson)

class ItemController:

   @addslash
   def get(self, playlist, item):
      return r.lindex("playlists:" + playlist, int(item))

   def delete(self, playlist, item):
      if len(item) <= 0:
         print "error"
         return self.write("")

      index = int(item)
      if (index < r.llen(PlaylistKey(playlist))):
         r.lset(PlaylistKey(playlist), item, "TO_DELETE")
         r.lrem(PlaylistKey(playlist), 0, "TO_DELETE")
         PublishChange(PlaylistKey(playlist), 'item', 'delete')
      self.set_status(204)
      return self.write("")

class Index(RequestHandler):
   @addslash
   def get(self):
      return self.render("index.html")


class Handler(WebSocketHandler):

   class ListenerThread(threading.Thread):
      def __init__(self, client, socket):
         threading.Thread.__init__(self)
         self.socket = socket
         self.client = client
         self.endThreadEvent = threading.Event()

      def run(self):
         while not self.endThreadEvent.isSet():
            for item in self.client.listen():
               if (item['type'] == 'message'):
                  self.socket.write_message(item['data'])

   def listen(self, channel):
      self.client = r.pubsub()
      self.channel = channel
      self.client.subscribe(self.channel)
      self.listener = self.ListenerThread(self.client, self)
      self.listener.setDaemon(True)
      self.listener.start()

   def on_message(self, msg):
      if msg.kind == 'message':
         self.write_message(msg.body)

   def open(self, playlist):
      self.listen(PlaylistKey(playlist))

   def on_close(self):
      self.client.unsubscribe(self.channel)
      self.listener.endThreadEvent.set()
      print "closed"
##########

settings = {
   "static_path": os.path.join(os.path.dirname(__file__), "static"),
   "template_path": os.path.join(os.path.dirname(__file__), "templates"),
   "debug": True
}


application = Application ([
   (r"/Playlists/([^/]+)/Items/([^/]+)/?", ItemController),
   (r"/Playlists/([^/]+)/Items/?", ItemsController),
   (r"/Playlists/([^/]+)/Tags/([^/]+)/?", TagController),
   (r"/Playlists/([^/]+)/Tags/?", TagsController),
   (r"/Playlists/([^/]+)/?", PlaylistController),
   (r"/Playlists/?", PlaylistsController),
   (r"/", Index)
], **settings)

def set_ping(ioloop, timeout):
   ioloop.add_timeout(timeout, lambda: set_ping(ioloop, timeout))

if __name__ == "__main__":
   application.listen(8888)
   HTTPServer(Application([(r'/Playlists/(.*)/', Handler)])).listen(7657)
   ioloop = tornado.ioloop.IOLoop.instance()
   set_ping(ioloop, timedelta(seconds=2))
   ioloop.start()
