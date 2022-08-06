import http.client
import urllib.parse
import time
import threading
import os
import sys

if not os.path.exists("settings.conf"):
	open("settings.conf", "w").close()
f = open("settings.conf", "r")
content = f.read().split("\n")
f.close()
channel_dict = {}

period = -1
base_url = None
should_download = False
resolution = None
display_unchanged_things = False

def get_url(url):
	conn = http.client.HTTPSConnection(url)
	conn.request("GET", "/")
	response = conn.getresponse()
	conn.close()
	conn = http.client.HTTPSConnection("redirect.invidious.io")
	conn.request("GET", "/")
	response = conn.getresponse()
	data = response.read().decode()
	conn.close()
	possible_list = list(map(lambda x: x.split(">")[-1], data.split("instances-list")[1].split("</ul>")[0].split("</a>")))
	for possibility in possible_list:
		try:
			print("Trying", possibility)
			conn = http.client.HTTPSConnection(possibility)
			conn.request("GET", "/")
			response = conn.getresponse()
			conn.close()
			print(response.status, response.reason)
			if response.status in [200, 302]:
				return possibility
		except:
			pass
	print("Could not find a valid server")
	raise KeyError()

def watch_for_changes(event, url, period):
	print("Looking for updates")
	i = 1
	while not event.is_set():
		conn = http.client.HTTPSConnection(url)
		for channel in channel_dict:
			conn.request("GET", "/channel/" + channel)
			response = conn.getresponse()
			while response.status != 200:
				print(response.status, response.reason)
				conn.close()
				print("Updating URL. Current URL:", url)
				url = get_url(url)
				print("New URL:", url)
				conn = http.client.HTTPSConnection(url)
				print(url, "/channel/" + channel)
				conn.request("GET", "/channel/" + channel)
				response = conn.getresponse()
				conn.close()
			text = response.read().decode()
			videos = set(filter(lambda y: not "&" in y and not "DOCTYPE" in y, map(lambda x: x.split("\"")[0], text.split("href=\"/watch?v="))))
			if len(videos.difference(channel_dict[channel])) != 0:
				print("UPDATE FOUND")
				print("Channel:", text.split("<title>")[1].split("</title>")[0])
				vid_diff = list(filter(lambda x: not x in channel_dict[channel], videos))
				for diff in vid_diff:
					channel_dict[channel].add(diff)
					title = text.split(diff + "\">")[1].split("</a>")[0].split("<p dir=\"auto\">")[1].split("</p>")[0]
					print("Title:", title)
					if should_download:
						print("Downloading", )
						payload = urllib.parse.urlencode({"id": diff, "title": title, "download_widget": '{"itag": ' + '22' if resolution == "720p" else '18' + ', "ext":"mp4"}'})
						conn.request("POST", "/download", headers={"Content-Type": "x-www-form-urlencoded"}, body=payload)
						response = conn.getresponse()
						if response.status != 302:
							print(response.status)
							raise KeyError()
						conn.request("GET", list(filter(lambda x: x[0] == "Location", response.getheaders()))[0][1])
						response = response.getresponse()
						f = open("downloads/" + title + ".mp4", "wb")
						f.write(response.read())
						f.close()
			elif display_unchanged_things:
				print("No updates found for", channel)
		print("checked", i, "times")
		event.wait(period)
		i += 1
		conn.close()
	return url

for line in content:
	if line == "":
		continue
	if line.startswith("|"):
		if line.startswith("|period="):
			period = int(line.split("=")[1])
		if line.startswith("|base_url="):
			base_url = line.split("=")[1]
		if line.startswith("|should_download="):
			should_download = line.split("=")[1] == "true"
		if line.startswith("|resolution"):
			resolution = line.split("=")[1]
		if line.startswith("|display_unchanged_things"):
			display_unchanged_things = line.split("=")[1] == "true"
	else:
		tup = line.split("|")
		if len(tup) != 2 or tup[0] in channel_dict:
			raise KeyError()
		channel_dict[tup[0]] = set(tup[1].split("&"))

if period == -1:
	period = 5
if not base_url:
	base_url = "vid.puffyan.us"
	

while True:
	print("Currently tracked channels:")
	for channel in channel_dict:
		print(channel)
	print("---------------------------")
	print("1: Start watching for changes every", period, "seconds")
	print("2: Change period")
	print("3: Add a channel")
	print("4: Remove a channel")
	print("5: Change downloading status")
	print("6: Change displaying unchanged things")
	print("q: Exit")
	option = input("---------------------------\n")
	if option == "1":
		#watch_for_changes(base_url, period)
		event = threading.Event()
		thread = threading.Thread(target = watch_for_changes, args=(event, base_url, period))
		thread.start()
		input("Press any key to interrupt\n")
		print("STOPPING")
		event.set()
	elif option == "2":
		print("Current period:", period)
		period = int(input("New period in seconds: "))
	elif option == "3":
		id = input("New channel's id: ")
		if id in channel_dict:
			print("Channel already exists")
			raise KeyError()
		conn = http.client.HTTPSConnection(base_url)
		conn.request("GET", "/channel/" + id)
		channel_dict[id] = list(filter(lambda y: not "&" in y and not "DOCTYPE" in y, map(lambda x: x.split("\"")[0], conn.getresponse().read().decode().split("href=\"/watch?v="))))
	elif option == "4":
		for channel in channel_dict:
			print(channel)
		channel_dict.remove(input("Channel to delete: "))
	elif option == "5":
		print("Current value:", should_download)
		should_download = input("New value: ") == "true"
	elif option == "6":
		print("Current value:", display_unchanged_things)
		display_unchanged_things = input("New value: ") == "true"
	elif option == "q":
		break

f = open("settings.conf", "w")
f.write("|period=" + str(period) + "\n")
f.write("|base_url=" + base_url + "\n")
f.write("|display_unchanged_things=" + str(display_unchanged_things) + "\n")
if resolution:
	f.write("|resolution=" + resolution + "\n")
f.write("|should_download=" + str(should_download).lower() + "\n")
for channel in channel_dict:
	f.write(channel + "|" + "&".join(channel_dict[channel]) + "\n")

f.close()