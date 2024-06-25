import requests
import subprocess
import time
import threading
import os
import sys
import datetime
import re
import json
from typing import Optional, TypedDict

class Settings(TypedDict):
	period: int
	base_url: str
	display_unchanged_things: bool
	download_folder: str
	should_reattempt_failed_downloads: bool
	should_download: bool
	failed_downloads: list[str]
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
	settings = Settings(period=1800, base_url="yt.cdaut.de", display_unchanged_things=False, download_folder="./downloads/", should_reattempt_failed_downloads=True, should_download=True, failed_downloads=[], tracked_channels={})

if settings["should_download"] and not os.path.exists(settings["download_folder"]):
	os.mkdir(settings["download_folder"])

url: str = settings['base_url']

def update_url():
	global url
	global failed_urls
	print("searching for a replacement for", url)
	if not url in failed_urls:
		print("Appending", url, "to", failed_urls)
		failed_urls.append(url)
		print(failed_urls)
	data = requests.get(f'https://redirect.invidious.io').text
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
			response = requests.get(f'https://{url}/watch?v=dQw4w9WgXcQ', timeout=20)
		except:
			print("Exception while trying", possibility)
			if not possibility in failed_urls:
				failed_urls.append(possibility)
			continue
		print(response.status_code, response.reason)
		if response.status_code in [200, 302]:
			url = possibility
			return
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
				response = requests.get(url)
			except:
				pass
			print(response.status_code, response.reason)
			if response.status_code in [200, 302]:
				print(possibility, "to the rescue")
				failed_urls.remove(possibility)
				url = possibility
				return
	print("All urls were exhausted, sorry")
	raise KeyError()

def print_channels(url: str):
	global settings
	channels_to_delete: list[str] = []
	for channel in settings['tracked_channels']:
		response = requests.get(f'https://{url}/api/v1/channels/{channel}')
		if response.status_code != 200:
			answer = input(f'Could not get a valid response for {channel}\nDelete it? (Yes/No)')
			if answer == 'Yes':
				channels_to_delete.append(channel)
			continue
		j = response.json()
		name = j['author']
		print(f'{channel}: {name}')
	for channel in channels_to_delete:
		del settings['tracked_channels'][channel]

def update_incomplete_read_count():
	global incomplete_read_count
	incomplete_read_count += 2
	if incomplete_read_count >= incomplete_read_reload:
		incomplete_read_count = 0
		update_url()
	else:
		print(f'({incomplete_read_count}/{incomplete_read_reload})')

def download_video(vid_id: str, timeout: Optional[int]) -> bool:
	global settings
	itag = "22"
	try:
		vid_info = requests.get(f'https://{url}/api/v1/videos/{vid_id}').json()
		if vid_info['liveNow'] or vid_info['isUpcoming']:
			return False
		sanitized_name = re.sub(r'\W+', '_', f'{vid_info["author"]}-{vid_info["title"]}').removesuffix('_') + '.mp4'
		print('\tDownloading')
		payload = {'itag': itag, 'id': vid_id, 'local': 'true'}
		response = requests.get(f'https://{url}/latest_version', params=payload)
		if response.status_code not in [200, 404]:
			update_incomplete_read_count()
			return False
		folder_name = os.path.join(settings['download_folder'], str(datetime.date.fromtimestamp(time.time()).isoformat()))
		if not os.path.exists(folder_name):
			os.mkdir(folder_name)
		if response.status_code == 404:
			print("\tCould not download in 720p, trying to splice")
			payload = {'itag': '399', 'id': vid_id, 'local': 'true'}
			response = requests.get(f'https://{url}/latest_version', params=payload, stream=True)
			if response.status_code == 200:
				read_size = 0
				with open('tmp.mp4', 'wb') as f:
					for chunk in response.iter_content(chunk_size=1024):
						f.write(chunk)
						read_size += 1
						print(f'\x0d\t\t{read_size}kiB', end='')
				print()
				print("\tDownloaded video only")
				payload = {'itag': '140', 'id': vid_id, 'local': 'true'}
				response = requests.get(f'https://{url}/latest_version', params=payload, stream=True)
				read_size = 0
				with open('tmp.mp4a', 'wb') as f:
					for chunk in response.iter_content(chunk_size=1024):
						f.write(chunk)
						read_size += 1
						print(f'\x0d\t\t{read_size}kiB', end='')
				print()
				print("\tDownloaded audio only")
				subprocess.run(['ffmpeg', '-i', 'tmp.mp4', '-i', 'tmp.mp4a', '-c', 'copy', os.path.join(folder_name, sanitized_name)], capture_output=False)
				return True
			else:
				print("\tCould not splice, trying in 360p")
				payload = {'itag': '18', 'id': vid_id, 'local': 'true'}
				response = requests.get(f'https://{url}/latest_version', params=payload)
				if response.status_code != 200:
					return False
		read_size = 0
		with open(os.path.join(folder_name, sanitized_name), 'wb') as f:
			for chunk in response.iter_content(chunk_size=1024):
				f.write(chunk)
				read_size += 1
				print(f'\x0d\t\t{read_size}kiB', end='')
		print()
	except Exception as e:
		print(e)
		update_incomplete_read_count()
		return False
	print('\tDownload done')
	return True

def watch_for_changes(event: threading.Event):
	global settings
	global incomplete_read_count
	print('Looking for updates')
	i = 0
	while not event.is_set():
		print(f'Starting to look now: {datetime.datetime.fromtimestamp(time.time())}')
		for channel in settings['tracked_channels']:
			if event.is_set():
				return
			try:
				response = requests.get(f'https://{url}/api/v1/playlists/{channel}')
				playlist_json = response.json()
			except Exception as e:
				print(e)
				update_url()
				continue
			if response.status_code != 200:
				continue
			diffs = list(filter(lambda x: x['videoId'] not in settings['tracked_channels'][channel], playlist_json['videos']))
			if len(diffs) != 0:
				diffs.reverse()
				print(f'UPDATE FOUND IN CHANNEL {playlist_json["author"]} ({playlist_json["authorId"]})')
				for diff in diffs:
					if event.is_set():
						return
					print(f'{diff["title"]} ({diff["videoId"]})')
					video_id = diff['videoId']
					if settings['should_download']:
						if video_id in settings['failed_downloads']:
							print('Skipping failed downloads')
						else:
							if not download_video(vid_id=video_id, timeout=600):
								if not video_id in settings['failed_downloads']:
									settings['failed_downloads'].append(video_id)
								continue
					settings['tracked_channels'][channel].append(video_id)
			elif settings['display_unchanged_things']:
				print("No updates found for", channel)
		if settings['should_reattempt_failed_downloads'] and len(settings['failed_downloads']) > 0:
			print('Reattempting failed downloads')
			to_remove = []
			print('before:', len(settings['failed_downloads']))
			for failed in settings['failed_downloads']:
				print(f'Reattempting {failed}')
				if event.is_set():
					return
				if download_video(failed, timeout=60):
					to_remove.append(failed)
			for failed in to_remove:
				video_info = requests.get(f'https://{url}/api/v1/videos/{failed}').json()
				print(f"Removing {video_info['title']} ({failed}) by {video_info['author']}")
				settings['tracked_channels'][video_info['authorId']].append(failed)
				settings['failed_downloads'].remove(failed)
			print('after:', len(settings['failed_downloads']))
			print('Done reattempting')
		i += 1
		print(f"Checked {i} times, next update: {datetime.datetime.fromtimestamp(time.time() + settings['period'])}")
		event.wait(settings['period'])

def add_channel(channel_id):
	global settings
	if channel_id in settings['tracked_channels']:
		return
	channel_json = requests.get(f'https://{url}/api/v1/playlists/{channel_id}').json()
	settings['tracked_channels'][channel_id] = list(set(list(map(lambda x: x['videoId'], channel_json['videos']))))

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
	print(f"8: Change reattempts at failed downloads ({settings['should_reattempt_failed_downloads']})")
	print(f"9: Change the base url ({settings['base_url']})")
	print("10: Print all channel names")
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
		settings['base_url'] = input("New value: ")
	elif option == "10":
		print_channels(settings['base_url'])
	elif option == "q":
		break

with open(path, 'w', encoding='utf-8') as f:
	f.write(json.dumps(settings))
