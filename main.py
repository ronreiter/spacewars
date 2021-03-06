from tornado.ioloop import IOLoop, PeriodicCallback
from tornado.database import Connection
import tornado.web as web
import tornadio2
import hashlib
import random
import time

# the port which the web application listens to
APP_PORT = 8080

# the session cookie name
SESSION_COOKIE_NAME = "session"

# the available colors of the players
COLORS = ["red", "green", "yellow", "orange", "purple", "blue", "teal"]

# this array will hold the players and their state
players = {}

# this list will hold all the current shots in the game
shots = []

# an incrementing counter of the player IDs that are allocated
current_player_id = 1

def random_color():
	"""Gets a random color"""
	return random.choice(COLORS)

def create_random_str():
	"""Gets a random string"""
	return hashlib.sha256(str(random.getrandbits(1000))).hexdigest()

def get_random_position():
	"""Gets the initial position of a player"""
	return [random.random() * 100 - 50,0,random.random() * 100 - 50]

def distance(a, b):
	"""This function calculates the distance between two 2D vectors"""
	return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5

class SessionManager:
	"""A session manager which works by getting a persistent dictionary to a user,
	identified by a cookie (using the request handler)."""
	sessions = {}

	@classmethod
	def get(cls, handler):
		session_id = handler.get_cookie(SESSION_COOKIE_NAME)
		if (not session_id) or (session_id not in cls.sessions.keys()):
			session_id = create_random_str()
			while session_id in cls.sessions.keys():
				session_id = create_random_str()
			handler.set_cookie(SESSION_COOKIE_NAME, session_id)
			cls.sessions[session_id] = {}

		return cls.sessions[session_id]

	@classmethod
	def get_by_session_id(cls, session_id):
		return cls.sessions.get(session_id)

class WebHandler(web.RequestHandler):
	"""Returns the main web application."""
	def get(self, *args, **kw):
		self.render("index.html")

class EventHandler(tornadio2.SocketConnection):
	"""Handles socket.IO messages"""
	def on_open(self, request):
		"""Called when a new player joins and connects to the server"""
		global current_player_id

		print "client connected."

		# initialize a new player
		self.id = current_player_id
		self.name = "Ron"
		self.color = random_color()
		self.position = get_random_position()
		self.rotation = [0,0,0]
		self.velocity = [0,0,0]
		self.health = 100
		self.score = 0
		self.thrust = 0
		self.rotationX = 0
		self.rotationY = 0

		current_player_id += 1

		# initializes the game on the client
		self.emit("start", self.id, self.name, self.color, self.position, self.rotation, self.health, self.score)

		for conn in players.values():
			# send to all connections a new player
			conn.emit("addPlayerView", self.id, self.name, self.color, self.position, self.rotation, self.velocity, self.thrust, self.rotationX, self.rotationY, self.health, self.score)

			# send all players to current connection
			self.emit("addPlayerView", conn.id, conn.name, conn.color, conn.position, conn.rotation, conn.velocity, conn.thrust, conn.rotationX, conn.rotationY, conn.health, conn.score)

		players[self.id] = self

	def on_close(self):
		print "connection closed."

		# remove player from all connected clients
		for conn in players.values():
			conn.emit("removePlayerView", self.id)

		del players[self.id]

	@tornadio2.event
	def updatePlayerInfo(self, position, rotation, velocity, thrust, rotationX, rotationY, health):
		"""An event which the client sends to update the player's info on the server"""

		self.position = position
		self.rotation = rotation
		self.velocity = velocity
		self.thrust = thrust
		self.rotationX = rotationX
		self.rotationY = rotationY
		self.health = health

		# update player info in all other clients
		for conn in players.values():
			if conn is self:
				continue
			conn.emit("updatePlayerView", self.id, self.position, self.rotation, self.velocity, self.thrust, self.rotationX, self.rotationY)

	@tornadio2.event
	def shot(self, position, rotation, speed, matrix):
		"""An event which the client sends to create a new shot"""
		shots.append([position, matrix, speed, 0, self])

		# sends all the players in the game the new shot
		for conn in players.values():
			conn.emit("shotView", self.id, position, rotation, speed)

class WebApp(object):
	"""This class represents the web application."""
	def __init__(self):
		# initializes the router
		app_router = tornadio2.TornadioRouter(EventHandler)

		# initializes the routes
		routes = [
			(r"/static/(.*)", web.StaticFileHandler, {"path": "./static"}),
			(r"/", WebHandler),
		]

		routes.extend(app_router.urls)

		self.application = web.Application(routes, socket_io_port = APP_PORT, debug = 1)

	def start(self, port = APP_PORT):
		"""Starts the web application."""
		self.application.listen(port)


def callback():
	"""The timer callback, advances the world"""
	global last_time

	# time_diff is the amount of time which has passed since the last call
	# to this function.
	time_diff = time.time() - last_time
	last_time = time.time()

	# process the shots
	for shot in shots:
		# move the shots according to the shot direction.
		# the shot orientation (shot[1]) is the orientation matrix. the vector 8-9-10 is the Z direction
		# of the shot, which we need to add. We can do this also by multiplying the matrix with [0,0,1].
		shot[0][0] -= shot[1][8] * time_diff * shot[2]
		shot[0][1] -= shot[1][9] * time_diff * shot[2]
		shot[0][2] -= shot[1][10] * time_diff * shot[2]

		# advance the shot timer as well
		shot[3] += time_diff

		# check for collision
		for target in players.values():
			shooter = shot[4]

			# check if the shot's distance is small enough to call it a hit
			if distance(target.position, shot[0]) < 10 and target is not shooter:
				print "BOOM! %s fired at %s" % (shooter.id, target.id)

				# reduce the player health
				if target.health > 0:
					target.health -= 5

					# update health on all clients
					for conn in players.values():
						conn.emit("updatePlayerHealth", target.id, target.health)

				else:
					# game over, restart player
					target.position = get_random_position()
					target.rotation = [0,0,0]
					target.health = 100
					shooter.score += 1

					# update score on all clients
					for conn in players.values():
						conn.emit("updatePlayerScore", shooter.id, shooter.score)

					print "%s killed %s, score: %s" % (shooter.id, target.id, shooter.score)
					target.emit("start", target.id, target.name, target.color, target.position, target.rotation, target.health, target.score)

				# remove the shot on hit
				shots.remove(shot)
				break

		# remove the shot if 1 second has passed since it was spawned
		if shot[3] > 1.0:
			shots.remove(shot)

last_time = time.time()
main_loop = IOLoop.instance()

# starts the web application and the
WebApp().start()

# starts the periodic callback timer to advance the world
PeriodicCallback(callback, 50, io_loop = main_loop).start()

# start the main loop
main_loop.start()

