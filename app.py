from flask import Flask, render_template, request, jsonify, send_from_directory
import pandas as pd
import requests
import time
from math import radians, sin, cos, sqrt, atan2
import os
from pathlib import Path

app = Flask(__name__, 
    static_folder='public',
    template_folder='public'
)

class CourseService:
    def __init__(self):
        self.api_key = '674239fafbc08091cf2f2c8bd6fa128a'
        self.df = None
        self.address_cache = {}  # 地址坐标缓存
        self.load_data()
    
    def load_data(self):
        """加载课程数据和缓存"""
        try:
            # 使用统一的数据文件路径
            data_dir = Path('public/data')
            files = [f for f in data_dir.glob('*经纬度*.xlsx')]
            if not files:
                raise FileNotFoundError("未找到经纬度数据文件")
            
            # 按文件名日期排序，使用最新的文件
            latest_file = sorted(files)[-1]
            self.df = pd.read_excel(latest_file)
            
            # 加载缓存
            if '经度' in self.df.columns and '纬度' in self.df.columns:
                for _, row in self.df.iterrows():
                    if pd.notna(row['经度']) and pd.notna(row['纬度']):
                        cache_key = f"{row['城市']}:{row['具体地址']}"
                        self.address_cache[cache_key] = [str(row['经度']), str(row['纬度'])]
                    
            print(f"已加载数据文件：{latest_file}")
        except Exception as e:
            print(f"加载数据出错: {e}")
            raise

    def get_coordinates(self, address, city='上海'):
        """获取地址的经纬度（带缓存）"""
        cache_key = f"{city}:{address}"
        # 检查缓存
        if cache_key in self.address_cache:
            return self.address_cache[cache_key]

        # 确保地址包含城市名
        if not any(prefix in address for prefix in [f'{city}', f'{city}市']):
            address = f"{city}市{address}"

        # 调用高德API
        url = "https://restapi.amap.com/v3/geocode/geo"
        params = {
            'address': address,
            'key': self.api_key,
            'city': city,
            'output': 'JSON'
        }
        
        try:
            response = requests.get(url, params=params)
            data = response.json()
            
            if data['status'] == '1' and data['geocodes']:
                # 验证返回的地址是否在指定城市
                formatted_address = data['geocodes'][0]['formatted_address']
                if not formatted_address.startswith(f'{city}市'):
                    print(f"警告：地址不在{city}: {address} -> {formatted_address}")
                    return None, None
                    
                location = data['geocodes'][0]['location']
                coords = location.split(',')
                # 更新缓存
                self.address_cache[cache_key] = coords
                return coords
            return None, None
        except Exception as e:
            print(f"请求出错: {e}")
            return None, None

    def find_nearby_courses(self, address, district=None, class_type=None, course_type=None, city='上海'):
        """查找附近课程"""
        print(f"开始查询课程")
        print(f"筛选条件: 区域={district}, 班型={class_type}, 课程类型={course_type}")
        
        # 判断是否需要计算距离
        need_distance = bool(address and address.strip())
        
        # 只查询同城市的课程
        city_courses = self.df[self.df['城市'] == city]
        print(f"同城市课程数量: {len(city_courses)}")
        
        # 应用筛选条件
        if district:
            city_courses = city_courses[city_courses['行政区'] == district]
        if class_type:
            city_courses = city_courses[city_courses['班型'] == class_type]
        if course_type:
            city_courses = city_courses[city_courses['课程分类'] == course_type]
        
        print(f"找到{len(city_courses)}个符合条件的课程")
        
        results = []
        
        # 如果需要计算距离，先获取用户坐标
        user_coords = None
        if need_distance:
            user_coords = self.get_coordinates(address, city)
            print(f"用户地址坐标: {user_coords}")
            if not user_coords[0]:
                return {"error": "无法获取地址坐标"}
        
        # 处理每个课程
        for _, row in city_courses.iterrows():
            result = {
                "课程名称": row['课程'],
                "地址": row['具体地址']
            }
            
            if need_distance:
                course_coords = self.get_coordinates(row['具体地址'], city)
                if not course_coords[0]:
                    continue
                distance = self.calculate_distance(
                    float(user_coords[1]), float(user_coords[0]),
                    float(course_coords[1]), float(course_coords[0])
                )
                result.update({
                    "距离": round(distance, 1),
                    "coords": course_coords  # 临时保存坐标
                })
            results.append(result)

        # 处理结果
        if need_distance:
            # 按距离排序并只取前5个
            results.sort(key=lambda x: x['距离'])
            results = results[:5]
            print("开始获取前5个课程的路线信息...")
            # 只为最近的5个课程获取路线信息
            for result in results:
                coords = result.pop('coords')  # 移除临时坐标
                result['route_info'] = self.get_route_info(
                    user_coords[0], user_coords[1],
                    coords[0], coords[1]
                )
        else:
            # 纯筛选模式，最多返回20条结果
            results = results[:20]

        return {"results": results}

    def calculate_distance(self, lat1, lon1, lat2, lon2):
        """计算两点之间的距离（单位：公里）"""
        R = 6371  # 地球半径（公里）
        
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        distance = R * c
        
        return distance

    def get_route_info(self, origin_lng, origin_lat, dest_lng, dest_lat):
        """获取路线规划信息"""
        print(f"开始获取路线信息: {origin_lng},{origin_lat} -> {dest_lng},{dest_lat}")
        time.sleep(0.5)  # 控制API调用频率

        # 驾车路线
        driving_url = "https://restapi.amap.com/v3/direction/driving"
        driving_params = {
            'key': self.api_key,
            'origin': f"{origin_lng},{origin_lat}",
            'destination': f"{dest_lng},{dest_lat}",
            'extensions': 'all'  # 获取详细信息
        }
        
        # 公交路线
        transit_url = "https://restapi.amap.com/v3/direction/transit/integrated"
        transit_params = {
            'key': self.api_key,
            'origin': f"{origin_lng},{origin_lat}",
            'destination': f"{dest_lng},{dest_lat}",
            'city': '上海',
            'extensions': 'all'  # 获取详细信息
        }
        
        try:
            print("请求驾车路线...")
            driving_response = requests.get(driving_url, params=driving_params).json()
            print("驾车路线响应:", driving_response.get('status'))
            
            print("请求公交路线...")
            transit_response = requests.get(transit_url, params=transit_params).json()
            print("公交路线响应:", transit_response.get('status'))
            
            route_info = {
                'driving': {
                    'time': None,
                    'distance': None,
                    'steps': []
                },
                'transit': {
                    'time': None,
                    'walking_distance': 0,
                    'steps': []
                }
            }
            
            if driving_response['status'] == '1' and driving_response['route']['paths']:
                path = driving_response['route']['paths'][0]
                route_info['driving'].update({
                    'time': int(path['duration']) // 60,
                    'distance': round(float(path['distance']) / 1000, 1),
                    'steps': [step['instruction'] for step in path['steps']]
                })
            
            if transit_response['status'] == '1' and transit_response['route']['transits']:
                transit = transit_response['route']['transits'][0]
                route_info['transit'].update({
                    'time': int(transit['duration']) // 60,
                    'steps': []
                })
                
                # 处理每一段行程
                for segment in transit['segments']:
                    # 处理步行部分
                    if segment.get('walking'):
                        route_info['transit']['walking_distance'] += float(segment['walking']['distance'])
                        route_info['transit']['steps'].append({
                            'type': 'walking',
                            'distance': round(float(segment['walking']['distance'])),
                            'duration': int(segment['walking']['duration']) // 60
                        })
                    
                    # 处理地铁/公交部分
                    if segment.get('bus'):
                        for line in segment['bus']['buslines']:
                            route_info['transit']['steps'].append({
                                'type': 'transit',
                                'name': line['name'],
                                'departure': line['departure_stop']['name'],
                                'arrival': line['arrival_stop']['name'],
                                'stops': int(line['via_num']) + 1,
                                'duration': int(line['duration']) // 60
                            })
                
            return route_info
            
        except Exception as e:
            print(f"获取路线信息出错: {e}")
            return None

course_service = CourseService()

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/search', methods=['POST'])
def search():
    data = request.json
    address = data.get('address', '').strip()
    filters = data.get('filters', {})
    city = data.get('city', '上海')
    
    has_filters = any(filters.values())
    if not address and not has_filters:
        return jsonify({"error": "请输入地址或选择筛选条件"}), 400
    
    results = course_service.find_nearby_courses(
        address,
        district=filters.get('district'),
        class_type=filters.get('class_type'),
        course_type=filters.get('course_type'),
        city=city
    )
    return jsonify(results)

@app.route('/filters', methods=['GET'])
def get_filters():
    """获取所有可用的筛选选项"""
    city = request.args.get('city', '上海')
    return jsonify({
        'districts': sorted(course_service.df[course_service.df['城市'] == city]['行政区'].unique().tolist()),
        'class_types': sorted(course_service.df[course_service.df['城市'] == city]['班型'].unique().tolist()),
        'course_types': sorted(course_service.df[course_service.df['城市'] == city]['课程分类'].unique().tolist())
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True, port=5001)  # 换成5001端口 