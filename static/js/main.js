var ytplayer;
var playlistID;
var playlistJson;
$(function() {
   $("#SearchTerm").keyup(function() {
      OnTextChanged(encodeURIComponent($(this).val()));
   });
   $("#TagSearchTerm").keyup(function () {
      OnSearchTags(encodeURIComponent($(this).val()));
   });
  $("#AddTag").keyup(function(event) {
      if (event.which == 13) {
         addToTags($(this).val());
         $(this).val('');
      }
   });

   SetupPlaylistName();

   SetupClickHandlers();

   if (playlistJson) {
      loadPlaylistItems(playlistJson.items);
      loadPlaylistTags(playlistJson.tags);
   }
   connectSocket();
});

var activeReq;
function OnTextChanged(searchTerm)
{
   if (activeReq != undefined)
      activeReq.abort();
   activeReq = $.ajax({
      url: "https://gdata.youtube.com/feeds/api/videos?q=" + searchTerm + "&max-results=5&alt=json&v=2",
      type: "GET",
      dataType: 'jsonp',
      success: function(msg) {
         $("#SearchResults").html("");
         $.each(msg.feed.entry, function(count) {
            this.docId = "result"+count;
            $("#SearchResults").append(tmpl("video_template", this));
            $("#"+this.docId).data('video', this);
         });
      }
   });
}

function addToPlaylist(vid) {
   $.ajax({
      url: 'Items/',
      data: JSON.stringify(vid),
      type: 'POST'
   });
}

function PlayVideo(videoElement) {
   videoId = $(videoElement).data('video').media$group.yt$videoid.$t;
   if (ytplayer) {
      ytplayer.loadVideoById(videoId, 0);
   }
   else {
      var params = { allowScriptAccess: "always" };
      var atts = {id: "myytplayer" };
      swfobject.embedSWF("http://www.youtube.com/v/" + videoId + "&enablejsapi=1&playerapiid=ytplayer&version=3", "ytapiplayer", "350", "300", "8", null, null, params, atts);
   }
   $('.NowPlaying').removeClass('NowPlaying');
   $(videoElement).addClass('NowPlaying');
   $("#NPTitle").html($(videoElement).data('video').title.$t);
}

function OnVideoStateChanged(state)
{
   if (state == 0) {
      var nextVid = $('.NowPlaying').next('.video');
      PlayVideo(nextVid);
   }
}
function onYouTubePlayerReady(playerId) {
   ytplayer = document.getElementById("myytplayer");
   ytplayer.addEventListener("onStateChange", "OnVideoStateChanged");
   ytplayer.playVideo();
}

function addToTags(tagName) {
   $.ajax({
      url: 'Tags/',
      data: tagName,
      type: 'POST'
   });
}

function connectSocket() {
   var options = {transports:['flashsocket', 'htmlfile', 'xhr-polling', 'jsonp-polling'], rememberTransport: false};
   var sock = new io.connect('http://' + window.location.hostname + '?playlistid='+playlistID, options);
   sock.on('connect', function() {
      $("#greeting").html("Socket connected");
   });

   sock.on('message', function(msg) {
      $("#greeting").html("message received: " + msg);
      var info = JSON.parse(msg);
      if (info.type == 'tag') {
         refreshTags();
      } else if (info.type == 'item') {
         refreshItems();
      }
   });

   sock.onclose = function() {
      $("#greeting").html("socket closed");
   }
}

function refreshItems() {
   $.ajax({
      url:'Items/',
      type:'GET',
      success: function(data) {
         loadPlaylistItems(JSON.parse(data));
      }
   });
}

function refreshTags() {
   $.ajax({
      url:'Tags/',
      type:'GET',
      success: function(data) {
         loadPlaylistTags(JSON.parse(data));
      }
   });
}


function loadPlaylistItems(playlist) {
   $("#PlaylistItems").html("");
   $.each(playlist, function(count) {
      this.docId = "playlistItem"+count;
      $("#PlaylistItems").append(tmpl("video_template", this));
      $("#"+this.docId).data('index', count);
      $("#"+this.docId).data('video', this);
   });

}

function loadPlaylistTags(tags) {
   $("#PlaylistTagsList").html("");
   $.each(tags, function(count) {
      tagId = 'playlistTag'+count;
      tag = {'name':this, 'tagId':tagId };
      $("#PlaylistTagsList").append(tmpl("tag_template", tag));
      $("#"+tagId).data('tagName', this);
   });
}


function SetupPlaylistName() {
    $("#PlaylistName").on('click', 'span', function() {
      var input = $('<input />', {'type': 'text', 'name': 'PlaylistNameEdit', 'value': $(this).html()});
      $(this).hide();
      $(this).parent().append(input);
      input.focus();
   });

   $("#PlaylistName").on('blur', 'input', function(evt) {
      $("#PlaylistName > span").show();
      $("#PlaylistName > span").html($(this).val());
      $.ajax({
         url:'?name='+$(this).val(),
         type:'PUT'
      });
      $(this).remove();
   });

   $("#PlaylistName").on('keydown', 'input', function(evt) {
      if (evt.keyCode == undefined || evt.keyCode == 13) {
            $(this).blur();
            return;
      }
   });
}

function SetupClickHandlers() {
   $(".VideoContainer").on("click", ".video", function() {
      PlayVideo(this);
   });

   $("#SearchResults").on("click", ".ActionItem", function(e) {
      e.cancelBubble = true;
      if (e.stopPropagation) {
         e.stopPropagation();
      }

      addToPlaylist($(this).parent().data('video'));
   });

   $("#PlaylistTagsList").on("click", ".DeleteTag", function() {
      $.ajax({
         url:'Tags/'+$(this).parent().data('tagName')+'/',
         type:'DELETE'
      });
   });

   $("#PlaylistItems").on("click", ".ActionItem", function(e) {
      e.cancelBubble = true;
      if (e.stopPropagation) {
         e.stopPropagation();
      }

      $.ajax({
         url:'Items/'+$(this).parent().data('index')+'/',
         type:'DELETE'
      });
   });

   $("#CreatePlaylist").click(function(e) {
      e.preventDefault();
      $.ajax({
         url: "/Playlists/",
         type: "POST",
         success: function(msg, respStatus, request) {
            if (request.status == 201) {
               window.location.href = request.getResponseHeader('Location');
            }
         },
      });
   });

   $("#TagSearchResults").on("click", ".TagSearchResult", function() {

   });
}

function OnSearchTags(tag) {
   $("#TagSearchResults").html("");
   $.ajax({
      url:'/Playlists?tag='+tag,
      type:'GET',
      success: function(data) {
         var results = JSON.parse(data);
         $.each(results, function(count) {
            this.docId = "TagSearchResult"+count;
            $("#TagSearchResults").append(tmpl("tag_search_result_tmpl", this));
            $("#TagSearchresult"+count).data('playlistInfo', this);
         });
      }
   });
}
