# Copyright(c) 2019 Livox Technology Company Limited.

cmake_minimum_required(VERSION 3.0.2)
include(cmake/version.cmake)
project(livox_ros_driver VERSION ${LIVOX_ROS_DRIVER_VERSION} LANGUAGES CXX)

find_package(Boost 1.54 REQUIRED COMPONENTS system thread chrono)
find_package(catkin REQUIRED COMPONENTS
  message_generation pcl_ros rosbag roscpp rospy sensor_msgs std_msgs)
find_package(PCL REQUIRED)
find_package(PkgConfig REQUIRED)
pkg_check_modules(APR apr-1)

add_message_files(FILES CustomPoint.msg CustomMsg.msg)
generate_messages(DEPENDENCIES std_msgs)

catkin_package(CATKIN_DEPENDS
  message_runtime pcl_ros rosbag roscpp rospy sensor_msgs std_msgs)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Livox Avia uses the original Livox-SDK (not Livox-SDK2). setup_workspace.sh
# installs it into this workspace so no root-owned /usr/local files are needed.
set(LIVOX_SDK_ROOT "${CMAKE_SOURCE_DIR}/../.deps/livox-sdk-install"
    CACHE PATH "Livox-SDK installation prefix")
find_path(LIVOX_SDK_INCLUDE_DIR livox_sdk.h
  PATHS "${LIVOX_SDK_ROOT}/include" NO_DEFAULT_PATH)
find_library(LIVOX_SDK_LIBRARY NAMES livox_sdk_static
  PATHS "${LIVOX_SDK_ROOT}/lib" NO_DEFAULT_PATH)
if(NOT LIVOX_SDK_INCLUDE_DIR OR NOT LIVOX_SDK_LIBRARY)
  message(FATAL_ERROR
    "Livox-SDK was not found under ${LIVOX_SDK_ROOT}. Run ./setup_workspace.sh first.")
endif()

link_directories(${PCL_LIBRARY_DIRS})
add_definitions(${PCL_DEFINITIONS})

add_executable(${PROJECT_NAME}_node
  livox_ros_driver/lvx_file.cpp
  livox_ros_driver/ldq.cpp
  livox_ros_driver/lds.cpp
  livox_ros_driver/lds_lvx.cpp
  livox_ros_driver/lds_lidar.cpp
  livox_ros_driver/lds_hub.cpp
  livox_ros_driver/lddc.cpp
  livox_ros_driver/livox_ros_driver.cpp
  timesync/timesync.cpp
  timesync/user_uart/user_uart.cpp
  common/comm/comm_protocol.cpp
  common/comm/sdk_protocol.cpp
  common/comm/gps_protocol.cpp)
target_compile_options(${PROJECT_NAME}_node PRIVATE -Wall)
add_dependencies(${PROJECT_NAME}_node ${PROJECT_NAME}_generate_messages_cpp)
target_include_directories(${PROJECT_NAME}_node PUBLIC
  ${catkin_INCLUDE_DIRS} ${PCL_INCLUDE_DIRS} ${APR_INCLUDE_DIRS}
  ${LIVOX_SDK_INCLUDE_DIR}
  common common/rapidjson common/rapidxml common/comm
  timesync timesync/user_uart livox_ros_driver)
target_link_libraries(${PROJECT_NAME}_node
  ${LIVOX_SDK_LIBRARY} ${Boost_LIBRARIES} ${catkin_LIBRARIES}
  ${PCL_LIBRARIES} ${APR_LIBRARIES})

install(TARGETS ${PROJECT_NAME}_node
  RUNTIME DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION})
install(DIRECTORY launch config DESTINATION ${CATKIN_PACKAGE_SHARE_DESTINATION})
