def playlist_key(playlist):
   return 'playlists:' + playlist

def tags_key(playlist):
   return 'playlists:%s:tags' % playlist

def tag_key(tag):
   return 'tags:' + tag

def playlist_name_key(playlist):
   return 'playlists:%s:name' % playlist

def names_key(name):
   return 'names:'+ name
