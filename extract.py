#! /usr/bin/python3
# -*- coding: utf-8 -*-

# Copyright (C) 2018 Julien Langlois
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import ctypes
import os
import struct
import sys

ABCT_HEADER_SIZE = 512 # AdbBackupControlType
DEFAULT_TWDATA_SIZE = 1024 * 1024 # 1MB

def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("action", choices=["list"])
	parser.add_argument("file_ab_twrp", type=argparse.FileType("rb"))
	parser.add_argument("--interractive", "-i", action="store_true", default=False)
	parser.add_argument("--auto-fix", action="store_true", default=False)

	args = parser.parse_args()

	files = load_image(args.file_ab_twrp, args)
	if not files:
		sys.exit(1)

	for item in files: #.values():
		print("  *", item["name"])
		if "real_size" in item:
			print("     declared size:", pretty_size(item["size"]), "(%d)" % item["size"])
			print("     real size:    ", pretty_size(item["real_size"]), "(%d)" % item["real_size"])
		else:
			print("     size:", pretty_size(item["size"]), "(%d)" % item["size"])

		print("     md5:", item["md5"])
		print("     data sequence:")
		for seq in item["sequence"]:
			print("       ",seq[0], " x ", seq[1])
	
	print()

	if args.interractive:
		for item in files:
			res = input("Do you want to export {filename}? [Y/n]?".format(filename=os.path.basename(item["name"])))
			if res.strip().lower() not in "y":
				continue

			print("  Exporting...")
			export_file(args.file_ab_twrp, item)


def load_image(stream, args):
	info = read_ctrl_block(stream)
	if not info or info["type"] != "twstreamheader":
		print("Invalid image")
		return

	print(info)

	files = []
	for i in range(info["partition_count"]):
		f_item = load_file(stream, args)
		if not f_item:
			print("Unable to retrieve file #"+str(i))
			return

		files.append(f_item)

	info = read_ctrl_block(stream)
	if not info or info["type"] != "twendadb":
		print("Invalid image footer")
		return

	return files


def load_file(stream, args):
	info = read_ctrl_block(stream)
	if not info:
		return

	if info["type"] not in ["twimage", "twfilename"]:
		return

	file_info = {
		"name": info["name"],
		"size": info["size"],
		"pos": stream.tell() - ABCT_HEADER_SIZE,
	}

	file_info["nb_chunks"] = info["size"] // (DEFAULT_TWDATA_SIZE-ABCT_HEADER_SIZE)
	file_info["last_size"] = info["size"] - (file_info["nb_chunks"] * (DEFAULT_TWDATA_SIZE-ABCT_HEADER_SIZE))

	sequence = [(file_info["nb_chunks"], DEFAULT_TWDATA_SIZE)]
	if file_info["last_size"]:
		sequence.append((1, file_info["last_size"] + ABCT_HEADER_SIZE))

	size_to_seek = sum([a*b for a,b in sequence] )
	stream.seek(size_to_seek, 1)

	info = read_ctrl_block(stream)
	if not info or info["type"] != "md5trailer":
		print("Invalid file trailer")
		
		info = load_file_search(stream, file_info)
		if not info:
			return
	else:
		file_info["sequence"] = sequence

	file_info["md5"] = info["md5"]
	return file_info


def load_file_search(stream, file_info):
	# first packet is less than 1 MB. And last packet same. Size attribute is wrong.
	# but in the middle, all packet are 1MB

	stream.seek(file_info["pos"]+ABCT_HEADER_SIZE)
	info = read_ctrl_block(stream)
	if not info or info["type"] != "twdatablock":
		print("Auto-fix: unable to process since first twdatablock is invalid")
		return False
	
	data = stream.read(DEFAULT_TWDATA_SIZE)
	stream.seek(-DEFAULT_TWDATA_SIZE, 1)

	pos = data.find(b"TWRP")
	if pos == -1:
		print("Auto-fix: unable to find next twdatablock after first one")
		return False

	sequence = [(1, pos + ABCT_HEADER_SIZE)]
	stream.seek(pos, 1)
	
	regular = True
	nb = 0
	while regular:
		stream.seek(DEFAULT_TWDATA_SIZE, 1)
		info = read_ctrl_block(stream)
		if not info or info["type"] != "twdatablock":
			regular = False
			stream.seek(-DEFAULT_TWDATA_SIZE, 1)
			continue
		
		nb+=1
		stream.seek(-ABCT_HEADER_SIZE, 1)

	if nb == 0:
		return False

	sequence.append((nb, DEFAULT_TWDATA_SIZE))

	stream.seek(ABCT_HEADER_SIZE, 1)
	data = stream.read(DEFAULT_TWDATA_SIZE)
	stream.seek(-len(data), 1)

	oo = 0
	found_pos = None
	while oo < len(data):
		pos = data.find(b"TWRP", oo+1)
		if pos == -1:
			print("Auto-fix: unable to find last twdatablock end position")
			return False

		stream.seek(pos, 1)
		info = read_ctrl_block(stream)
		stream.seek(-pos, 1)
		if info:
			stream.seek(-ABCT_HEADER_SIZE, 1)
			found_pos = pos
			break
		
		oo = pos
	
	if not found_pos:
		print("not found")
		return

	sequence.append((1, found_pos + ABCT_HEADER_SIZE))
	
	stream.seek(found_pos, 1)

	info = read_ctrl_block(stream)
	if not info or info["type"] != "md5trailer":
		return False

	file_info["sequence"] = sequence
	
	file_info["real_size"] = 0
	for (nb, size_t) in sequence:
		file_info["real_size"]+= nb * (size_t-ABCT_HEADER_SIZE)

	return info


def export_file(stream, file_info):
	name = os.path.basename(file_info["name"])
	stream.seek(file_info["pos"])
	stream.seek(ABCT_HEADER_SIZE, 1)

	with open(name, "wb") as f:
		for (nb, size_t) in file_info["sequence"]:
			for i in range(nb):
				stream.seek(ABCT_HEADER_SIZE, 1)
				f.write(stream.read(size_t  -ABCT_HEADER_SIZE))


def extract_string(data):
	pos = data.find(b"\0")
	if pos == -1:
		return data[:].decode("ascii")
	
	return data[:pos].decode("ascii")


def pretty_size(bytes_size):
	if bytes_size < 1024:
		return "%d" % bytes_size
	
	bytes_size = bytes_size/1024.0
	if bytes_size < 1024:
		return "%.2fKB" % bytes_size

	bytes_size = bytes_size/1024.0
	if bytes_size < 1024:
		return "%.2fMB" % bytes_size

	bytes_size = bytes_size/1024.0
	return "%.2fGB" % bytes_size


def read_ctrl_block(stream):
	b_start = stream.read(8)
	b_type = stream.read(16)

	try:
		b_start = extract_string(b_start)
		b_type = extract_string(b_type)
	except UnicodeDecodeError:
		print("not a control block", b_start, b_type)
		stream.seek(-24, 1)
		return
	
	infos = {"type": b_type}
	
	if b_type == "twstreamheader":
		infos["partition_count"] = struct.unpack("<Q", stream.read(ctypes.sizeof(ctypes.c_uint64)))[0]
		infos["version"] = struct.unpack("<Q", stream.read(ctypes.sizeof(ctypes.c_uint64)))[0]
		infos["crc"] = struct.unpack("<L", stream.read(ctypes.sizeof(ctypes.c_uint32)))[0]
		stream.seek(468, 1)

	elif b_type == "twimage" or b_type == "twfilename":
		infos["size"] = struct.unpack("<Q", stream.read(ctypes.sizeof(ctypes.c_uint64)))[0]
		infos["compressed"] = struct.unpack("<Q", stream.read(ctypes.sizeof(ctypes.c_uint64)))[0]
		infos["crc"] = struct.unpack("<L", stream.read(ctypes.sizeof(ctypes.c_uint32)))[0]
		infos["name"] = extract_string(stream.read(468))

	elif b_type == "twdatablock":
		infos["crc"] = struct.unpack("<L", stream.read(ctypes.sizeof(ctypes.c_uint32)))[0]
		stream.seek(484, 1)

	elif b_type == "md5trailer":
		infos["crc"]  = struct.unpack("<L", stream.read(ctypes.sizeof(ctypes.c_uint32)))[0]
		infos["ident"]  = struct.unpack("<L", stream.read(ctypes.sizeof(ctypes.c_uint32)))[0]
		infos["md5"] = extract_string(stream.read(40))
		stream.seek(440, 1)

	elif b_type == "twendadb":
		infos["crc"] = struct.unpack("<L", stream.read(ctypes.sizeof(ctypes.c_uint32)))[0]
		stream.seek(484, 1)

	else:
		print("unknown type",b_type)
		stream.seek(-24, 1)
		return

	return infos


if __name__ == "__main__":
	main()
