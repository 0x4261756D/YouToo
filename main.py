import http.client
import urllib.parse
import time
import threading
import os
import sys
import datetime
import re
import json
from typing import Optional, TypedDict

class Fail(TypedDict):
	channel: str
	title: str
	channel_name: str

class Settings(TypedDict):
	period: int
	base_url: str
	display_unchanged_things: bool
	download_folder: str
	should_reattempt_failed_downloads: bool
	resolution: str
	should_download: bool
	failed_downloads: dict[str, Fail]
	tracked_channels: dict[str, list[str]]

incomplete_read_count: int = 0
incomplete_read_reload: int = 5
failed_urls: list[str] = []

path = 'settings.json'

if not os.path.exists(path):
	open(path, "w").close()
try:
	with open(path, "r", encoding="utf-8") as f:
		settings: Settings = json.loads(f.read())
except Exception as e:
	settings = Settings(period=1800, base_url="yt.cdaut.de", display_unchanged_things=False, download_folder="./downloads/", should_reattempt_failed_downloads=True, resolution="720p", should_download=True, failed_downloads={}, tracked_channels={})

if settings["should_download"] and not os.path.exists(settings["download_folder"]):
	os.mkdir(settings["download_folder"])

def get_url(url: str) -> str:
	global failed_urls
	print("searching for a replacement for", url)
	if not url in failed_urls:
		print("Appending", url, "to", failed_urls)
		failed_urls.append(url)
		print(failed_urls)
	conn = http.client.HTTPSConnection("redirect.invidious.io")
	conn.request("GET", "/")
	response = conn.getresponse()
	data = response.read().decode()
	conn.close()
	print(failed_urls)
	possible_list = list(map(lambda x: x.split(">")[-1], data.split("instances-list")[1].split("</ul>")[0].split("</a>")))
	for possibility in possible_list:
		if possibility == url:
			print("Skipping", possibility)
			continue
		if possibility in failed_urls:
			print("Skipping", possibility)
			continue
		print("Trying", possibility)
		try:
			conn = http.client.HTTPSConnection(possibility, timeout=20)
			conn.request("GET", "/watch?v=dQw4w9WgXcQ")
			response = conn.getresponse()
			conn.close()
		except:
			print("Exception while trying", possibility)
			if not possibility in failed_urls:
				failed_urls.append(possibility)
			continue
		print(response.status, response.reason)
		if response.status in [200, 302]:
			return possibility
		elif not possibility in failed_urls:
			failed_urls.append(possibility)
	print("Could not find a valid server")
	if len(failed_urls) > 0:
		print("Retrying previously failed urls")
		for possibility in failed_urls:
			if possibility == url:
				continue
			print("Trying", possibility)
			try:
				conn = http.client.HTTPSConnection(possibility)
				conn.request("GET", "/")
				response = conn.getresponse()
				conn.close()
			except:
				pass
			print(response.status, response.reason)
			if response.status in [200, 302]:
				print(possibility, "to the rescue")
				failed_urls.remove(possibility)
				return possibility
	print("All urls were exhausted, sorry")
	raise KeyError()

def print_channels(url: str):
	global settings
	channels_to_delete: list[str] = []
	conn = http.client.HTTPSConnection(url)
	for channel in settings['tracked_channels']:
		conn.request("GET", f"/channel/{channel}")
		response = conn.getresponse()
		if response.status != 200:
			answer = input(f"Could not get a valid response for {channel}\nDelete it? (Yes/No)")
			if answer == "Yes":
				channels_to_delete.append(channel)
			response.read()
			continue
		text = response.read().decode()
		name = text.split('og:title" content="')[1].split('"')[0]
		print(f"{channel}: {name}")
	for channel in channels_to_delete:
		del settings['tracked_channels'][channel]

def download_video(conn, url, video_url, title, channel_name, timeout: Optional[float]):
	global settings
	global incomplete_read_count
	quality_string = '{"itag":18,"ext":"mp4"}'
	if settings['resolution'] == "720p":
		quality_string = '{"itag":22,"ext":"mp4"}'
	payload = urllib.parse.urlencode({"id": video_url, "title": title, "download_widget": quality_string})
	conn.request("POST", "/download", headers={"Content-Type": "application/x-www-form-urlencoded"}, body=payload)
	try:
		response = conn.getresponse()
	except Exception as e:
		print(e)
		conn.close()
		incomplete_read_count += 2
		if incomplete_read_count >= incomplete_read_reload:
			incomplete_read_count = 0
			url = get_url(url)
		else:
			print(f"({incomplete_read_count}/{incomplete_read_reload})")
		return False
	conn.close()
	if response.status != 302:
		print(response.status, payload)
		print(response.read().decode())
		print("Could not get the correct status code")
		incomplete_read_count += 1
		if incomplete_read_count >= incomplete_read_reload:
			incomplete_read_count = 0
			url = get_url(url)
			print("New url:", url)
		else:
			print(f"({incomplete_read_count}/{incomplete_read_reload})")
		return False
	print("Got the video url")
	conn = http.client.HTTPSConnection(url, timeout=timeout)
	conn.request("GET", list(filter(lambda x: x[0] == "Location", response.getheaders()))[0][1])
	print("Downloading")
	response = conn.getresponse()
	sanitized_title = re.sub(r'\W+', '_', channel_name).removesuffix("_") + "-" + re.sub(r'\W+', '_', title).removesuffix("_")
	folder_name = os.path.join(settings['download_folder'], str(datetime.date.fromtimestamp(time.time()).isoformat()))
	if not os.path.exists(folder_name):
		os.mkdir(folder_name)
	f = open(folder_name + "/" + sanitized_title + ".mp4", "wb")
	try:
		vid = response.read()
		if len(vid) == 0:
			print("The downloaded video was empty, response code:", response.status)
			f.close()
			print("Updating URL, current URL:", url)
			url = get_url(url)
			print("New URL:", url)
			return False
		f.write(vid)
	except Exception as e:
		print(e)
		conn.close()
		f.close()
		incomplete_read_count += 2
		if incomplete_read_count >= incomplete_read_reload:
			incomplete_read_count = 0
			url = get_url(url)
		else:
			print(f"({incomplete_read_count}/{incomplete_read_reload})")
		return False
	f.close()
	print("Download done")
	return True

def watch_for_changes(event: threading.Event, url):
	global settings
	global incomplete_read_count
	print("Looking for updates")
	i = 1
	while not event.is_set():
		print(f"Starting to look now: {datetime.datetime.fromtimestamp(time.time())}")
		conn = http.client.HTTPSConnection(url)
		for channel in settings['tracked_channels']:
			if event.is_set():
				return
			conn.request("GET", "/playlist?list=" + channel)
			try:
				response = conn.getresponse()
				text = response.read().decode()
			except Exception as e:
				print(e)
				conn.close()
				url = get_url(url)
				continue
			while response.status != 200 and not event.is_set():
				print(response.status, response.reason)
				conn.close()
				print("Updating URL. Current URL:", url)
				url = get_url(url)
				print("New URL:", url)
				conn = http.client.HTTPSConnection(url)
				print(url, "/playlist?list=" + channel)
				try:
					conn.request("GET", "/playlist?list=" + channel)
					response = conn.getresponse()
					text = response.read().decode()
				except Exception as e:
					print(e)
				conn.close()
			videos = set(list(map(lambda x: x.split("&list=")[0], text.split('href="/watch?v=')))[1:])
			if len(videos.difference(settings['tracked_channels'][channel])) != 0:
				print("UPDATE FOUND:", channel)
				if len(text.split('class="channel-name"')) < 2:
					print("Could not find a title")
					incomplete_read_count += 2
					if incomplete_read_count >= incomplete_read_reload:
						incomplete_read_count = 0
						url = get_url(url)
					else:
						print(f"({incomplete_read_count}/{incomplete_read_reload})")
					with open("err.log", "w", encoding="utf-8") as f:
						f.write(text)
					conn.close()
					continue
				channel_name = text.split('class="channel-name"')[1].split("</p>")[0].split(">")[1].strip()
				print("Channel:", channel_name, '|')
				vid_diff = list(filter(lambda x: not x in settings['tracked_channels'][channel], videos))
				for diff in vid_diff:
					if event.is_set():
						return
					print(diff)
					if text.count(diff) < 3:
						print("could not find two instances of", diff)
						conn.close()
						incomplete_read_count += 2
						continue
					title = text.split(diff)[3].split('p dir="auto">')[1].split('</p>')[0].replace("&amp;", "&").replace("&#39;", "'").strip()
					print("Title:", title)
					if settings['should_download']:
						if diff in settings['failed_downloads']:
							print("Skipping failed download")
						else:
							while response.status != 200 and "Download is disabled" in text:
								print(response.status, response.reason)
								conn.close()
								print("Updating URL. Current URL:", url)
								url = get_url(url)
								print("New URL:", url)
								conn = http.client.HTTPSConnection(url)
								print(url, "/playlist?list=" + channel)
								conn.request("GET", "/playlist?list=" + channel)
								response = conn.getresponse()
								conn.close()
							conn.request('GET', f'/watch?v={diff}')
							response = conn.getresponse()
							vid_text = response.read().decode()
							response.close()
							if 'This live event will begin in' in vid_text:
								print('Skipping', title, 'because the stream has not started yet')
								continue
							else:
								if not download_video(conn, url, diff, title, channel_name, 600):
									if not diff in settings['failed_downloads']:
										settings['failed_downloads'][diff] = Fail(channel=channel, title=title, channel_name=channel_name)
									continue
					settings['tracked_channels'][channel].append(diff)
			elif settings['display_unchanged_things']:
				print("No updates found for", channel)
		if settings['should_reattempt_failed_downloads'] and len(settings['failed_downloads']) > 0:
			print("reattempting failed previous attempts")
			to_remove = []
			print("before:", len(settings['failed_downloads']))
			for failed in settings['failed_downloads']:
				print(f"Reattempting {settings['failed_downloads'][failed]}")
				if event.is_set():
					return
				if download_video(conn, url, video_url=failed, title=settings['failed_downloads'][failed]['title'], channel_name=settings['failed_downloads'][failed]['channel_name'], timeout=60):
					to_remove.append(failed)
			for failed in to_remove:
				print("removing", settings['failed_downloads'][failed])
				settings['tracked_channels'][settings['failed_downloads'][failed]['channel']].append(failed)
				settings['failed_downloads'].pop(failed)
			print("after:", len(settings['failed_downloads']))
			print("done reattempting")
		i += 1
		conn.close()
		print("checked", i, "times, next update: ", datetime.datetime.fromtimestamp(time.time() + settings['period']))
		event.wait(settings['period'])
	return url

def add_channel(id):
	global settings
	if id in settings['tracked_channels']:
		print("Channel already exists")
		raise KeyError()
	conn = http.client.HTTPSConnection(settings['base_url'])
	conn.request("GET", "/playlist?list=" + id)
	text = conn.getresponse().read().decode()
	settings['tracked_channels'][id] = list(set(list(map(lambda x: x.split("&list=")[0], text.split('href="/watch?v=')))[1:]))


while True:
	print("Currently tracked channels:")
	for channel in settings['tracked_channels']:
		print(channel)
	print("---------------------------")
	print("Current instance:", settings['base_url'])
	print("1: Start watching for changes every", settings['period'], "seconds")
	print(f"2: Change period ({settings['period']})")
	print("3: Add a channel")
	print("4: Remove a channel")
	print(f"5: Change downloading status ({settings['should_download']})")
	print(f"6: Change displaying unchanged things ({settings['display_unchanged_things']})")
	print("7: Read channel list from file")
	print(f"8: Change resolution to download ({settings['resolution']})")
	print(f"9: Change reattempts at failed downloads ({settings['should_reattempt_failed_downloads']})")
	print(f"10: Change the base url ({settings['base_url']})")
	print("11: Print all channel names")
	print("q: Exit")
	option = input("---------------------------\n")
	if option == "1":
		event = threading.Event()
		thread = threading.Thread(target = watch_for_changes, args=(event, settings['base_url']))
		thread.start()
		input("Press any key to interrupt\n")
		print("STOPPING")
		event.set()
	elif option == "2":
		print("Current period:", settings['period'])
		settings['period'] = int(input("New period in seconds: "))
	elif option == "3":
		id = input("New channel's id: ")
		add_channel(id)
	elif option == "4":
		for channel in settings['tracked_channels']:
			print(channel)
		del settings['tracked_channels'][input("Channel to delete: ")]
	elif option == "5":
		print("Current value:", settings['should_download'])
		settings['should_download'] = input("New value: ").lower() == "true"
	elif option == "6":
		print("Current value:", settings['display_unchanged_things'])
		settings['display_unchanged_things'] = input("New value: ") == "true"
	elif option == "7":
		fname = input("File location: ")
		if not os.path.exists(fname):
			print("File does not exist")
		else:
			channels = open(fname).readlines()
			for channel in channels:
				add_channel(channel.split(" ")[0].replace("\n", ""))
	elif option == "8":
		settings['resolution'] = input("New resolution: ")
	elif option == "9":
		settings['should_reattempt_failed_downloads'] = input("New value: ").lower() == "true"
	elif option == "10":
		settings['base_url'] = input("New value: ")
	elif option == "11":
		print_channels(settings['base_url'])
	elif option == "q":
		break

with open(path, 'w', encoding='utf-8') as f:
	f.write(json.dumps(settings))
