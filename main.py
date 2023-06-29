import http.client
import urllib.parse
import time
import threading
import os
import sys
import datetime
import re
from typing import Optional

if not os.path.exists("settings.conf"):
	open("settings.conf", "w").close()
f = open("settings.conf", "r", encoding="utf-8")
content = f.read().split("\n")
f.close()
channel_dict: dict = {}
failed_downloads: dict[str, tuple[str, str, str]] = {}

period = -1
base_url = None
should_download = False
should_reattempt_failed_downloads: bool = False
resolution = None
display_unchanged_things = False
download_folder = "downloads/"

failed_urls = []

def get_url(url: str) -> str:
	global failed_urls
	if not url in failed_urls:
		failed_urls.append(url)
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

incomplete_read_count = 0
incomplete_read_reload = 5

def download_video(conn, url, video_url, title, channel_name, timeout: Optional[float]):
	global failed_downloads
	global incomplete_read_count
	quality_string = '{"itag":18,"ext":"mp4"}'
	if resolution == "720p":
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
		else:
			print(f"({incomplete_read_count}/{incomplete_read_reload})")
		return False
	print("Got the video url")
	conn = http.client.HTTPSConnection(url, timeout=timeout)
	conn.request("GET", list(filter(lambda x: x[0] == "Location", response.getheaders()))[0][1])
	print("Downloading")
	response = conn.getresponse()
	sanitized_title = re.sub(r'\W+', '_', channel_name).removesuffix("_") + "-" + re.sub(r'\W+', '_', title).removesuffix("_")
	folder_name = download_folder + str(datetime.date.fromtimestamp(time.time()).isoformat())
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

def watch_for_changes(event: threading.Event, url, period):
	global channel_dict
	global failed_downloads
	global incomplete_read_count
	print("Looking for updates")
	i = 1
	while not event.is_set():
		print(f"Starting to look now: {datetime.datetime.fromtimestamp(time.time())}")
		conn = http.client.HTTPSConnection(url)
		for channel in channel_dict:
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
			if len(videos.difference(channel_dict[channel])) != 0:
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
				channel_name = text.split('class="channel-name"')[1].split("</p>")[0].split(">")[1]
				print("Channel:", channel_name)
				vid_diff = list(filter(lambda x: not x in channel_dict[channel], videos))
				for diff in vid_diff:
					if event.is_set():
						return
					title = text.split(diff)[2].split("</a>")[0].split("<p dir=\"auto\">")[1].split("</p>")[0].replace("&amp;", "&").replace("&#39;", "'")
					print("Title:", title)
					if should_download:
						if diff in failed_downloads and should_reattempt_failed_downloads:
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
							if not download_video(conn, url, diff, title, channel_name, 600):
								if not diff in failed_downloads:
									failed_downloads[diff] = (channel, title, channel_name)
								continue
					channel_dict[channel].add(diff)
			elif display_unchanged_things:
				print("No updates found for", channel)
		if should_reattempt_failed_downloads and len(failed_downloads) > 0:
			print("reattempting failed previous attempts")
			to_remove = []
			print("before:", len(failed_downloads))
			for failed in failed_downloads:
				if event.is_set():
					return
				if download_video(conn, url, failed, failed_downloads[failed][1], failed_downloads[failed][2], 60):
					to_remove.append(failed)
			for failed in to_remove:
				print("removing", failed_downloads[failed])
				channel_dict[failed_downloads[failed][0]].add(failed)
				failed_downloads.pop(failed)
			print("after:", len(failed_downloads))
			print("done reattempting")
		i += 1
		conn.close()
		print("checked", i, "times, next update: ", datetime.datetime.fromtimestamp(time.time() + period))
		event.wait(period)
	return url

for line in content:
	if line == "":
		continue
	if line.startswith("|"):
		if line.startswith("|period="):
			period = int(line.split("=")[1])
		elif line.startswith("|base_url="):
			base_url = line.split("=")[1]
		elif line.startswith("|should_download="):
			should_download = line.split("=")[1] == "True"
		elif line.startswith("|resolution"):
			resolution = line.split("=")[1]
		elif line.startswith("|display_unchanged_things"):
			display_unchanged_things = line.split("=")[1] == "True"
		elif line.startswith("|download_folder"):
			download_folder = line.split("=")[1]
		elif line.startswith("|should_reattempt_failed_downloads"):
			should_reattempt_failed_downloads = line.split("=")[1] == "True"
		elif line.startswith("|failed_downloads"):
			for failed in line.split("=")[1].split("%")[:-1]:
				if len(failed.split("|")) < 2:
					raise KeyError()
				failed_parts = failed.split("|")
				failed_val = "|".join(failed_parts[1:]).split(", ")
				print(failed_val)
				failed_downloads[failed_parts[0]] = (failed_val[0][2:-1], failed_val[1][1:-1], failed_val[2][1:-2])
	else:
		tup = line.split("|")
		if len(tup) != 2 or tup[0] in channel_dict:
			print(tup)
			raise KeyError()
		channel_dict[tup[0]] = set(tup[1].split("&"))

def add_channel(id):
	global channel_dict
	if id in channel_dict:
		print("Channel already exists")
		raise KeyError()
	conn = http.client.HTTPSConnection(base_url)
	conn.request("GET", "/playlist?list=" + id)
	text = conn.getresponse().read().decode()
	channel_dict[id] = set(list(map(lambda x: x.split("&list=")[0], text.split('href="/watch?v=')))[1:])
#	channel_dict[id] = list(filter(lambda y: not "&" in y and not "DOCTYPE" in y, map(lambda x: x.split("\"")[0], conn.getresponse().read().decode().split("href=\"/watch?v="))))


if period == -1:
	period = 5
if not base_url:
	base_url = "vid.puffyan.us"
if should_download and not os.path.exists(download_folder):
	os.mkdir(download_folder)

while True:
	print("Currently tracked channels:")
	for channel in channel_dict:
		print(channel)
	print("---------------------------")
	print("Current instance:", base_url)
	print("1: Start watching for changes every", period, "seconds")
	print(f"2: Change period ({period})")
	print("3: Add a channel")
	print("4: Remove a channel")
	print(f"5: Change downloading status ({should_download})")
	print(f"6: Change displaying unchanged things ({display_unchanged_things})")
	print("7: Read channel list from file")
	print(f"8: Change resolution to download ({resolution})")
	print(f"9: Change reattempts at failed downloads ({should_reattempt_failed_downloads})")
	print(f"10: Change the base url ({base_url})")
	print("q: Exit")
	option = input("---------------------------\n")
	if option == "1":
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
		add_channel(id)
	elif option == "4":
		for channel in channel_dict:
			print(channel)
		channel_dict.popitem(input("Channel to delete: "))
	elif option == "5":
		print("Current value:", should_download)
		should_download = input("New value: ").lower() == "true"
	elif option == "6":
		print("Current value:", display_unchanged_things)
		display_unchanged_things = input("New value: ") == "true"
	elif option == "7":
		fname = input("File location: ")
		if not os.path.exists(fname):
			print("File does not exist")
		else:
			channel_list = open(fname).readlines()
			for channel in channel_list:
				add_channel(channel.split(" ")[0].replace("\n", ""))
	elif option == "8":
		resolution = input("New resolution: ")
	elif option == "9":
		should_reattempt_failed_downloads = input("New value: ").lower() == "true"
	elif option == "10":
		base_url = input("New value: ")
	elif option == "q":
		break

f = open("settings.conf", "w", encoding="utf-8")
f.write("|period=" + str(period) + "\n")
f.write("|base_url=" + base_url + "\n")
f.write("|display_unchanged_things=" + str(display_unchanged_things) + "\n")
f.write("|download_folder=" + str(download_folder) + "\n")
f.write("|should_reattempt_failed_downloads=" + str(should_reattempt_failed_downloads) + "\n")
if len(failed_downloads) > 0:
	f.write(f"|failed_downloads=")
	for failed in failed_downloads:
		f.write(f"{failed}|{failed_downloads[failed]}%")
	f.write("\n")
if resolution:
	f.write("|resolution=" + resolution + "\n")
f.write("|should_download=" + str(should_download) + "\n")
for channel in channel_dict:
	f.write(channel + "|" + "&".join(channel_dict[channel]) + "\n")

f.close()