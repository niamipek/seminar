import redis

# Connect to Redis
r = redis.Redis(host='localhost', port=6379, db=0)
# Send a ping request and check the response
response = r.ping()
print("Response:", response)