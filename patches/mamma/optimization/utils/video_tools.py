import os
import os.path as osp
import subprocess
import glob
import argparse


def create_video_from_images(images_folder, output_path, extension="png",
                              base_name="img_", frame_rate=30):
    # Get a sorted list of image files
    images = sorted(glob.glob(osp.join(images_folder, f"{base_name}*.{extension}")))

    if not images:
        print("No images found in the specified folder.")
        return

    # Create a temporary text file listing the images
    list_file = osp.join(images_folder, "image_list.txt")
    with open(list_file, "w") as f:
        for img in images:
            f.write(f"file '{img}'\n")

    try:
        from imageio_ffmpeg import get_ffmpeg_exe
        ffmpeg_exe = get_ffmpeg_exe()
    except Exception:
        ffmpeg_exe = "ffmpeg"

    # Define the FFmpeg command
    ffmpeg_command = [
        ffmpeg_exe,
        "-r", f"{frame_rate}",  # Input framerate
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-vf", "scale=iw:ih",
        "-c:v", "libx264",
        "-crf", "23",
        "-r", f"{frame_rate}",
        "-pix_fmt", "yuv420p",
        "-y", output_path
    ]

    # Execute the FFmpeg command
    try:
        subprocess.run(ffmpeg_command, check=True)
        print(f"Video successfully created: {output_path}")
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error occurred while creating the video: {e}")
    finally:
        # Remove the temporary list file
        os.remove(list_file)


def arg_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images_folder", type=str, default="images")
    parser.add_argument("--output_path", type=str, default="output.mp4")
    parser.add_argument("--extension", type=str, default="png")
    parser.add_argument("--base_name", type=str, default="")
    parser.add_argument("--frame_rate", type=int, default=30)

    return parser.parse_args()


if __name__ == "__main__":
    args = arg_parser()
    create_video_from_images(args.images_folder, args.output_path,
                             args.extension, args.base_name, args.frame_rate)