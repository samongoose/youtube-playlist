def PlaylistKey(playlist):
   return 'playlists:' + playlist

def TagsKey(playlist):
   return 'playlists:%s:tags' % playlist

def TagKey(tag):
   return 'tags:' + tag

def PlaylistNameKey(playlist):
   return 'playlists:%s:name' % playlist

def NamesKey(name):
   return 'names:'+ name
