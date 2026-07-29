import socket

try:
    print(socket.getaddrinfo("db.wwluvmmofmbcmqgwbepy.supabase.co", 5432))
except Exception as e:
    print(repr(e))