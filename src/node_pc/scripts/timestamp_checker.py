#!/usr/bin/env python3
"""
Diagnostic script to analyze timestamp differences between:
- ROS sim time (from rosbag --clock)
- LiDAR header.stamp
- Camera header.stamp

Runs through all rosbag files and calculates the constant offset for each.
"""

import os
import sys
import glob
import subprocess
import time
import signal
import numpy as np

import rospy
import rosbag
from sensor_msgs.msg import PointCloud2, Image


def analyze_rosbag(bag_path):
    """Analyze a single rosbag file and return timestamp differences."""
    print(f"\n{'='*80}")
    print(f"Analyzing: {os.path.basename(bag_path)}")
    print('='*80)
    
    lidar_diffs = []
    camera_diffs = []
    
    try:
        bag = rosbag.Bag(bag_path, 'r')
        
        # Get bag info
        info = bag.get_type_and_topic_info()
        topics = info.topics
        
        print(f"Duration: {bag.get_end_time() - bag.get_start_time():.2f} seconds")
        print(f"Start time: {bag.get_start_time():.3f}")
        print(f"End time: {bag.get_end_time():.3f}")
        
        # Analyze LiDAR messages
        lidar_topic = "/livox/lidar"
        if lidar_topic in topics:
            print(f"\nLiDAR topic: {lidar_topic} ({topics[lidar_topic].message_count} messages)")
            for topic, msg, t in bag.read_messages(topics=[lidar_topic]):
                sim_time = t.to_sec()  # Time when message was recorded (sim time)
                msg_time = msg.header.stamp.to_sec()  # Header timestamp
                diff = sim_time - msg_time
                lidar_diffs.append(diff)
        else:
            print(f"\nWARNING: LiDAR topic {lidar_topic} not found!")
        
        # Analyze Camera messages
        camera_topic = "/camera/image_raw"
        if camera_topic in topics:
            print(f"Camera topic: {camera_topic} ({topics[camera_topic].message_count} messages)")
            for topic, msg, t in bag.read_messages(topics=[camera_topic]):
                sim_time = t.to_sec()  # Time when message was recorded (sim time)
                msg_time = msg.header.stamp.to_sec()  # Header timestamp
                diff = sim_time - msg_time
                camera_diffs.append(diff)
        else:
            print(f"WARNING: Camera topic {camera_topic} not found!")
        
        bag.close()
        
    except Exception as e:
        print(f"ERROR reading bag: {e}")
        return None, None
    
    # Calculate statistics
    results = {}
    
    if lidar_diffs:
        lidar_arr = np.array(lidar_diffs)
        results['lidar'] = {
            'mean': np.mean(lidar_arr),
            'std': np.std(lidar_arr),
            'min': np.min(lidar_arr),
            'max': np.max(lidar_arr),
            'count': len(lidar_arr)
        }
        print(f"\n[LIDAR] Offset (sim_time - header.stamp):")
        print(f"  Mean:   {results['lidar']['mean']:.6f} sec")
        print(f"  Std:    {results['lidar']['std']:.6f} sec")
        print(f"  Min:    {results['lidar']['min']:.6f} sec")
        print(f"  Max:    {results['lidar']['max']:.6f} sec")
        print(f"  Count:  {results['lidar']['count']}")
    
    if camera_diffs:
        camera_arr = np.array(camera_diffs)
        results['camera'] = {
            'mean': np.mean(camera_arr),
            'std': np.std(camera_arr),
            'min': np.min(camera_arr),
            'max': np.max(camera_arr),
            'count': len(camera_arr)
        }
        print(f"\n[CAMERA] Offset (sim_time - header.stamp):")
        print(f"  Mean:   {results['camera']['mean']:.6f} sec")
        print(f"  Std:    {results['camera']['std']:.6f} sec")
        print(f"  Min:    {results['camera']['min']:.6f} sec")
        print(f"  Max:    {results['camera']['max']:.6f} sec")
        print(f"  Count:  {results['camera']['count']}")
    
    return results, os.path.basename(bag_path)


def main():
    # Find all rosbag files
    script_dir = os.path.dirname(os.path.realpath(__file__))
    ws_dir = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))
    bag_dir = os.path.join(ws_dir, "Rosbag files")
    
    if not os.path.isdir(bag_dir):
        print(f"ERROR: Bag directory not found: {bag_dir}")
        sys.exit(1)
    
    bag_files = sorted(glob.glob(os.path.join(bag_dir, "*.bag")))
    
    if not bag_files:
        print(f"ERROR: No .bag files found in {bag_dir}")
        sys.exit(1)
    
    print(f"\nFound {len(bag_files)} rosbag file(s) in: {bag_dir}")
    for f in bag_files:
        print(f"  - {os.path.basename(f)}")
    
    # Analyze each bag
    all_results = []
    all_lidar_means = []
    all_camera_means = []
    
    for bag_path in bag_files:
        results, bag_name = analyze_rosbag(bag_path)
        if results:
            all_results.append((bag_name, results))
            if 'lidar' in results:
                all_lidar_means.append(results['lidar']['mean'])
            if 'camera' in results:
                all_camera_means.append(results['camera']['mean'])
    
    # Print summary
    print("\n")
    print("=" * 80)
    print("SUMMARY - TIMESTAMP OFFSETS (sim_time - header.stamp)")
    print("=" * 80)
    
    print("\n{:<30} {:>20} {:>20}".format("Rosbag File", "LiDAR Offset (sec)", "Camera Offset (sec)"))
    print("-" * 72)
    
    for bag_name, results in all_results:
        lidar_val = f"{results['lidar']['mean']:.6f}" if 'lidar' in results else "N/A"
        camera_val = f"{results['camera']['mean']:.6f}" if 'camera' in results else "N/A"
        print(f"{bag_name:<30} {lidar_val:>20} {camera_val:>20}")
    
    print("-" * 72)
    
    # Overall statistics
    print("\n" + "=" * 80)
    print("FINAL VALUES ACROSS ALL ROSBAGS")
    print("=" * 80)
    
    if all_lidar_means:
        lidar_overall = np.array(all_lidar_means)
        print(f"\n[LIDAR] Offset to ADD to header.stamp to get sim_time:")
        print(f"  Overall Mean:      {np.mean(lidar_overall):.6f} sec")
        print(f"  Deviation (std):   {np.std(lidar_overall):.6f} sec")
        print(f"  Min across bags:   {np.min(lidar_overall):.6f} sec")
        print(f"  Max across bags:   {np.max(lidar_overall):.6f} sec")
    
    if all_camera_means:
        camera_overall = np.array(all_camera_means)
        print(f"\n[CAMERA] Offset to ADD to header.stamp to get sim_time:")
        print(f"  Overall Mean:      {np.mean(camera_overall):.6f} sec")
        print(f"  Deviation (std):   {np.std(camera_overall):.6f} sec")
        print(f"  Min across bags:   {np.min(camera_overall):.6f} sec")
        print(f"  Max across bags:   {np.max(camera_overall):.6f} sec")
    
    # Calculate the offset needed to sync LiDAR to Camera
    if all_lidar_means and all_camera_means:
        lidar_mean = np.mean(all_lidar_means)
        lidar_std = np.std(all_lidar_means)
        camera_mean = np.mean(all_camera_means)
        
        print("\n" + "=" * 80)
        print("RECOMMENDED CONFIG VALUES FOR LIDAR TIMESTAMP SHIFT")
        print("=" * 80)
        
        print(f"\n[timestamp_offset] - Converts LiDAR device-relative time to Unix/sim time")
        print(f"  This is the large offset because LiDAR uses device time (~hours since power-on)")
        print(f"  while camera uses Unix time (seconds since 1970).")
        print(f"  Value: {lidar_mean:.6f} sec")
        print(f"  Std:   {lidar_std:.6f} sec")
        
        print(f"\n[capture_offset] - Sensor capture delay difference (configured separately)")
        print(f"  This compensates for the time delay between when LiDAR and Camera")
        print(f"  capture the same environmental event. This is determined experimentally.")
        print(f"  Current config value: 32.43 sec")
        
        print("\n" + "-" * 80)
        print("FORMULA USED IN lidar_timestamp_shift.cpp:")
        print("-" * 80)
        print("\n  new_lidar_stamp = header.stamp + timestamp_offset - capture_offset")
        print(f"\n  Example: new_stamp = 3848.80 + {lidar_mean:.2f} - 32.43")
        print(f"           new_stamp = {3848.80 + lidar_mean - 32.43:.2f} sec")
        
        print("\n" + "-" * 80)
        print("CONFIG FILE VALUES (pipeline.yaml):")
        print("-" * 80)
        print(f"\nlidar_timestamp_shift:")
        print(f"  timestamp_offset: {lidar_mean:.6f}  # LiDAR device time -> Unix/sim time")
        print(f"  capture_offset: 32.43              # Sensor capture delay compensation")


if __name__ == "__main__":
    main()
