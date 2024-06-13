import struct


class ComfyMethod:
    @staticmethod
    def is_api_json(data):
        return all("class_type" in v for v in data.values())

    # TODO: add image support
    @staticmethod
    def get_png_metadata(file_path):
        txt_chunks = {}

        with open(file_path, "rb") as file:
            # reading the PNG signature
            signature = file.read(8)
            if signature != b"\x89PNG\r\n\x1a\n":
                print("Not a valid PNG file")
                return

            while True:
                length_data = file.read(4)
                if not length_data:
                    break
                length = struct.unpack(">I", length_data)[0]
                chunk_type = file.read(4).decode("ascii")
                chunk_data = file.read(length)

                if chunk_type == "tEXt" or chunk_type == "comf":
                    keyword_end = chunk_data.find(b"\x00")
                    keyword = chunk_data[:keyword_end].decode("utf-8")
                    # get the text content
                    content = chunk_data[keyword_end + 1 :].decode("utf-8")
                    txt_chunks[keyword] = content

                # move to the next chunk
                file.read(4)

        return txt_chunks

    # parsing logic from the comfy repo
    @staticmethod
    def parse_exif_data(exif_data):
        is_little_endian = struct.unpack("<H", exif_data[:2])[0] == 0x4949

        def read_int(offset, is_little_endian, length):
            arr = exif_data[offset : offset + length]
            if length == 2:
                return struct.unpack("<H" if is_little_endian else ">H", arr)[0]
            elif length == 4:
                return struct.unpack("<I" if is_little_endian else ">I", arr)[0]

        ifd_offset = read_int(4, is_little_endian, 4)

        def parse_ifd(offset):
            num_entries = read_int(offset, is_little_endian, 2)
            result = {}

            for i in range(num_entries):
                entry_offset = offset + 2 + i * 12
                tag = read_int(entry_offset, is_little_endian, 2)
                _type = read_int(entry_offset + 2, is_little_endian, 2)
                num_values = read_int(entry_offset + 4, is_little_endian, 4)
                value_offset = read_int(entry_offset + 8, is_little_endian, 4)

                value = None
                if _type == 2:
                    value = exif_data[
                        value_offset : value_offset + num_values - 1
                    ].decode("utf-8")

                result[tag] = value

            return result

        ifd_data = parse_ifd(ifd_offset)
        return ifd_data

    @staticmethod
    def get_webp_metadata(file_path):
        txt_chunks = {}

        with open(file_path, "rb") as file:
            # read the WEBP signature
            signature = file.read(12)
            if signature[:4] != b"RIFF" or signature[8:12] != b"WEBP":
                print("Not a valid WEBP file")
                return

            offset = 12
            while offset < len(signature):
                chunk_type = file.read(4).decode("ascii")
                chunk_length = struct.unpack("<I", file.read(4))[0]

                if chunk_type == "EXIF":
                    # skipping the identifier "Exif\0\0"
                    file.read(6)
                    exif_data = ComfyMethod.parse_exif_data(file.read(chunk_length - 6))
                    for key, value in exif_data.items():
                        index = value.find(":")
                        txt_chunks[value[:index]] = value[index + 1 :]

                # move to the next chunk
                file.read(chunk_length)

        return txt_chunks
