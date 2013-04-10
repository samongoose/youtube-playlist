import os
import redis
import json

from os import path as op

_redis_url = os.getenv('REDISTOGO_URL', 'redis://localhost:6379')
redis_client = redis.from_url(_redis_url)

def publish_change(key, item_type, action):
    publish_info = {
        'action':action,
        'type':item_type
    }
    redis_client.publish(key, json.dumps(publish_info))

def playlist_key(playlist):
   return 'playlists:{}'.format(playlist)

def tags_key(playlist):
   return 'playlists:{}:tags'.format(playlist)

def tag_key(tag):
   return 'tags:{}'.format(tag)

def playlist_name_key(playlist):
   return 'playlists:{}:name'.format(playlist)

def names_key(name):
   return 'names:'.format(name)
