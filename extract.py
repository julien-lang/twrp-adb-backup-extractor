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

	args = parser.parse_args()
	rules = {
		"/data/media/0/TWRP/2018-01-24--19-38-14_KTU84PG901FXXU1ANI4/system.ext4.win": {
			"start": 1041408,
			"num_cycles": 2023,
			"end": 1043968,
			"known_pos": 13640192,
		},
		"/data/media/0/TWRP/2018-01-24--19-38-14_KTU84PG901FXXU1ANI4/data.ext4.win": {
			"start": 942592,
			"num_cycles": 5186,
			"end": 665088,
			"known_pos": 2136995840,
		},
	}

	files = load_image(args.file_ab_twrp, rules)
	if not files:
		sys.exit(1)


	for item in files: #.values():
		print("  *", item["name"])
		print("     size:", pretty_size(item["size"]), "(%d)" % item["size"])
		print("     md5:", item["md5"])
	
	print()

	if args.interractive:
		for item in files:
			res = input("Do you want to export {filename}? [Y/n]?".format(filename=os.path.basename(item["name"])))
			if res.strip().lower() not in "y":
				continue
			
			print("  Exporting...")
			export_file(args.file_ab_twrp, item, rules)


def load_image(stream, rules):
	info = read_ctrl_block(stream)
	if not info or info["type"] != "twstreamheader":
		print("Invalid image")
		return

	print(info)

	files = []
	for i in range(info["partition_count"]):
		f_item = load_file(stream, rules)
		if not f_item:
			print("Unable to retrieve file #"+str(i))
			return

		files.append(f_item)

	info = read_ctrl_block(stream)
	if not info or info["type"] != "twendadb":
		print("Invalid image footer")
		return

	return files


def load_file(stream, rules):
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

	if info["name"] in rules:
		rule_set = rules[info["name"]]

		stream.seek(rule_set["start"], 1)
		stream.seek(rule_set["num_cycles"] * (DEFAULT_TWDATA_SIZE), 1)
		stream.seek(rule_set["end"], 1)

		tot = rule_set["start"]-ABCT_HEADER_SIZE + rule_set["num_cycles"] * (DEFAULT_TWDATA_SIZE-ABCT_HEADER_SIZE) + rule_set["end"]-ABCT_HEADER_SIZE
		print(tot)
	else:
		size_to_seek = info["size"] + file_info["nb_chunks"]*ABCT_HEADER_SIZE + ABCT_HEADER_SIZE
		stream.seek(size_to_seek, 1)

	info = read_ctrl_block(stream)
	if not info or info["type"] != "md5trailer":
		print("Invalid file trailer")
		return

	file_info["md5"] = info["md5"]
	return file_info


def export_file(stream, file_info, rules):
	name = os.path.basename(file_info["name"])
	print("  *","pos", file_info["pos"])
	print("  *","# chunks", file_info["nb_chunks"])
	print("  *","last chunk size", file_info["last_size"])

	stream.seek(file_info["pos"])
	stream.seek(ABCT_HEADER_SIZE, 1)

	if file_info["name"] in rules:
		rule_set = rules[file_info["name"]]

		with open(name, "wb") as f:			
			print("first chunk", rule_set["start"])
			stream.seek(ABCT_HEADER_SIZE, 1)
			f.write(stream.read(rule_set["start"]-ABCT_HEADER_SIZE))

			for i in range(rule_set["num_cycles"]):
				stream.seek(ABCT_HEADER_SIZE, 1)
				f.write(stream.read(DEFAULT_TWDATA_SIZE  -ABCT_HEADER_SIZE))

			print("last chunk", rule_set["end"])
			stream.seek(ABCT_HEADER_SIZE, 1)
			f.write(stream.read(rule_set["end"]-ABCT_HEADER_SIZE))

	else:
		with open(name, "wb") as f:
			for i in range(file_info["nb_chunks"]):
				stream.seek(ABCT_HEADER_SIZE, 1)
				f.write(stream.read(DEFAULT_TWDATA_SIZE  -ABCT_HEADER_SIZE))

			if file_info["last_size"]:
				print("last one", file_info["last_size"])
				stream.seek(ABCT_HEADER_SIZE, 1)
				f.write(stream.read(file_info["last_size"]))


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
