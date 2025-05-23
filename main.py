import subprocess
import time
import threading
import os
import sys
import datetime
import re
import json
from typing import Optional, TypedDict
import innertube
import random

class Settings(TypedDict):
	period: int
	display_unchanged_things: bool
	download_folder: str
	should_reattempt_failed_downloads: bool
	should_download: bool
	failed_downloads: set[str]
	tracked_channels: dict[str, list[str]]
	reattempt_batch_size: int
	failed_downloads_names: dict[str, str]
	channel_names: dict[str, str]

path = 'settings.json'

client = innertube.InnerTube("WEB", proxies="socks5://127.0.0.1:9050")

if not os.path.exists(path):
	open(path, "w").close()
try:
	with open(path, "r", encoding="utf-8") as f:
		settings: Settings = json.loads(f.read())
		settings['failed_downloads'] = set(settings['failed_downloads'])
except Exception as e:
	settings = Settings(period=1800, display_unchanged_things=False, download_folder="./downloads/", should_reattempt_failed_downloads=True, should_download=True, failed_downloads=set(), tracked_channels={}, reattempt_batch_size=10)

if settings["should_download"] and not os.path.exists(settings["download_folder"]):
	os.mkdir(settings["download_folder"])
settings.setdefault('reattempt_batch_size', 10)
if settings["reattempt_batch_size"] <= 0:
	settings["reattempt_batch_size"] = 10
settings.setdefault("failed_downloads_names", {})
settings.setdefault("channel_names", {})

def print_channels():
	global settings
	channels_to_delete: list[str] = []
	for channel in settings['tracked_channels']:
		retry = True
		while retry:
			retry = False
			time.sleep(random.randint(0, 3))
			try:
				response = client.browse(channel)
				name = response["metadata"]["channelMetadataRenderer"]["title"]
				settings["channel_names"][channel] = name
				print(f'{channel}: {name}')
			except:
				print(f'Could not get info for {channel}.')
				answer = input('Press `r` to retry, `d` to delete.')
				if answer == 'd':
					channels_to_delete.append(channel)
				else:
					retry = answer == 'r'
	for channel in channels_to_delete:
		del settings['tracked_channels'][channel]

def download_videos(id_list: set[str]) -> bool:
	import yt_dlp
	folder_path = 'downloads/' + time.strftime("%Y_%m_%d")
	if not os.path.exists(folder_path):
		os.mkdir(folder_path)
	options = {'proxy': 'socks5://127.0.0.1:9050', 'outtmpl': f'{folder_path}/%(uploader)s_%(title)s_%(id)s.%(ext)s'}
	try:
		with yt_dlp.YoutubeDL(options) as ydl:
			error_code = ydl.download(id_list)
			if error_code != 0:
				print(f'Error code: {error_code}')
				return False
			return True
	except Exception as e:
		if "This live event" in str(e):
			return True
		if "has already been downloaded" in str(e):
			return True
		print(f'Exception: {e}')
		return False

def watch_for_changes(event: threading.Event):
	global settings
	print('Looking for updates')
	i = 0
	while not event.is_set():
		print(f'Starting to look now: {datetime.datetime.fromtimestamp(time.time())}')
		for channel in settings['tracked_channels']:
			if event.is_set():
				return
			event.wait(random.random() * 5)
			try:
				response = client.browse(f"VLUU{channel[2:]}")
			except Exception as e:
				print(e)
				continue
			*videos, continuation = response['contents']['twoColumnBrowseResultsRenderer']['tabs'][0]['tabRenderer']['content']['sectionListRenderer']['contents'][0]['itemSectionRenderer']['contents'][0]['playlistVideoListRenderer']['contents']
			diffs = list(filter(lambda x: x['playlistVideoRenderer']['videoId'] not in settings['tracked_channels'][channel], videos))
			if len(diffs) != 0:
				channel_name = response['header']['playlistHeaderRenderer']['ownerText']['runs'][0]['text']
				settings['channel_names'][channel] = channel_name
				print(f"{len(diffs)} UPDATE(S) FOUND IN CHANNEL {channel_name} ({channel})")
				for diff in diffs:
					if event.is_set():
						return
					title = diff['playlistVideoRenderer']['title']['runs'][0]['text']
					video_id = diff['playlistVideoRenderer']['videoId']
					settings['failed_downloads_names'][video_id] = f"{channel_name}: {title}"
					print(f"{title} ({video_id})")
					settings['tracked_channels'][channel].append(video_id)
				if settings['should_download']:
					ids = set(map(lambda x: x['playlistVideoRenderer']['videoId'], diffs))
					print(f"Now downloading {ids}")
					if not download_videos(ids):
						settings.setdefault('failed_downloads', set())
						settings['failed_downloads'].update(ids)
				while len(diffs) != 0 and 'continuationItemRenderer' in continuation.keys():
					continuation_token = continuation['continuationItemRenderer']['continuationEndpoint']['continuationCommand']['token']
					event.wait(random.random() * 5)
					try:
						more = client.browse(continuation=continuation_token)
					except Exception as e:
						print(e)
						break
					*videos, continuation = more['onResponseReceivedActions'][0]['appendContinuationItemsAction']['continuationItems']
					diffs = list(filter(lambda x: x['playlistVideoRenderer']['videoId'] not in settings['tracked_channels'][channel], videos))
					if len(diffs) == 0:
						break
					print(f"{len(diffs)} MORE UPDATES FOUND")
					if event.is_set():
						return
					for video in diffs:
						title = diff['playlistVideoRenderer']['title']['runs'][0]['text']
						video_id = diff['playlistVideoRenderer']['videoId']
						settings['failed_downloads_names'][video_id] = f"{channel_name}: {title}"
						print(f"{title} ({video_id})")
						settings['tracked_channels'][channel].append(video_id)
					if settings['should_download']:
						print(f"Now downloading {ids}")
						ids = set(map(lambda x: x['playlistVideoRenderer']['videoId'], diffs))
						if not download_videos(ids):
							settings['failed_downloads'].update(ids)
				if 'playlistVideoRenderer' in continuation.keys() and continuation['playlistVideoRenderer']['videoId'] not in settings['tracked_channels'][channel]:
					print('A LAST UPDATE FOUND')
					title = continuation['playlistVideoRenderer']['title']['runs'][0]['text']
					video_id = continuation['playlistVideoRenderer']['videoId']
					settings['failed_downloads_names'][video_id] = f"{channel_name}: {title}"
					print(f"{title} ({video_id})")
					settings['tracked_channels'][channel].append(video_id)
			elif settings['display_unchanged_things']:
				print(f"No updates found for {channel}")
		if settings['should_download'] and settings['should_reattempt_failed_downloads'] and len(settings['failed_downloads']) > 0:
			print(f'Reattempting {len(settings["failed_downloads"])} failed downloads')
			tmp = list(settings['failed_downloads'])
			print([settings["failed_downloads_names"].get(vid_id) for vid_id in tmp])
			for j in range(0, len(tmp), settings['reattempt_batch_size']):
				print(f'({j}-{j + settings["reattempt_batch_size"]})')
				if download_videos(tmp[j:j+settings['reattempt_batch_size']]):
					settings['failed_downloads'].difference_update(tmp[j:j+settings['reattempt_batch_size']])
		i += 1
		print(f"Checked {i} times, next update: {datetime.datetime.fromtimestamp(time.time() + settings['period'])}")
		event.wait(settings['period'])

def add_channel(channel_id):
	global settings
	if channel_id in settings['tracked_channels']:
		print(f"{channel_id} was already tracked")
		return
	try:
		response = client.browse(f"VLUU{channel_id[2:]}")
	except Exception as e:
		print(e)
	*videos, continuation = response['contents']['twoColumnBrowseResultsRenderer']['tabs'][0]['tabRenderer']['content']['sectionListRenderer']['contents'][0]['itemSectionRenderer']['contents'][0]['playlistVideoListRenderer']['contents']
	settings['tracked_channels'][channel_id] = []
	for video in videos:
		title = video['playlistVideoRenderer']['title']['runs'][0]['text']
		video_id = video['playlistVideoRenderer']['videoId']
		print(f"{title} ({video_id})")
		settings['tracked_channels'][channel_id].append(video_id)
	while len(videos) != 0 and 'continuationItemRenderer' in continuation.keys():
		continuation_token = continuation['continuationItemRenderer']['continuationEndpoint']['continuationCommand']['token']
		time.sleep(random.random() * 3)
		try:
			more = client.browse(continuation=continuation_token)
		except Exception as e:
			print(e)
			break
		*videos, continuation = more['onResponseReceivedActions'][0]['appendContinuationItemsAction']['continuationItems']
		videos = list(filter(lambda x: x['playlistVideoRenderer']['videoId'] not in settings['tracked_channels'][channel_id], videos))
		if len(videos) == 0:
			break
		for video in videos:
			title = video['playlistVideoRenderer']['title']['runs'][0]['text']
			video_id = video['playlistVideoRenderer']['videoId']
			print(f"{title} ({video_id})")
			settings['tracked_channels'][channel_id].append(video_id)
	if 'playlistVideoRenderer' in continuation.keys():
		title = continuation['playlistVideoRenderer']['title']['runs'][0]['text']
		video_id = continuation['playlistVideoRenderer']['videoId']
		print(f"{title} ({video_id})")
		settings['tracked_channels'][channel_id].append(video_id)

while True:
	print("Currently tracked channels:")
	for channel in settings['tracked_channels']:
		print(f"{channel} ({settings['channel_names'].get(channel)})")
	print("---------------------------")
	print("1: Start watching for changes every", settings['period'], "seconds")
	print(f"2: Change period ({settings['period']})")
	print("3: Add a channel")
	print("4: Remove a channel")
	print(f"5: Change downloading status ({settings['should_download']})")
	print(f"6: Change displaying unchanged things ({settings['display_unchanged_things']})")
	print("7: Read channel list from file")
	print(f"8: Change reattempts at failed downloads ({settings['should_reattempt_failed_downloads']})")
	print("9: Print all channel names")
	print(f"10: Change reattempt batch size ({settings['reattempt_batch_size']})")
	print("q: Exit")
	option = input("---------------------------\n")
	if option == "1":
		event = threading.Event()
		thread = threading.Thread(target = watch_for_changes, args=[event])
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
		settings['should_reattempt_failed_downloads'] = input("New value: ").lower() == "true"
	elif option == "9":
		print_channels()
	elif option == "10":
		settings['reattempt_batch_size'] = int(input("New value: "))
		if settings['reattempt_batch_size'] <= 0:
			settings['reattempt_batch_size'] = 10
	elif option == "q":
		break

with open(path, 'w', encoding='utf-8') as f:
	settings['failed_downloads'] = list(settings['failed_downloads'])
	f.write(json.dumps(settings))
