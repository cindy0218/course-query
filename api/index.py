from flask import Flask, render_template, request, jsonify, send_from_directory
import pandas as pd
import requests
import time
from math import radians, sin, cos, sqrt, atan2
import os
from pathlib import Path

app = Flask(__name__)

# 修改静态文件路径
app.static_folder = 'public'
app.template_folder = 'public'

class CourseService:
    def __init__(self):
        self.api_key = '674239fafbc08091cf2f2c8bd6fa128a'
        self.df = None
        self.address_cache = {}
        self.load_data()
    
    def load_data(self):
        """加载课程数据和缓存"""
        try:
            # Vercel 环境中的数据文件路径
            if os.environ.get('VERCEL'):
                data_dir = Path('public/data')
            else:
                data_dir = Path('public/data')
            
            print(f"当前目录: {os.getcwd()}")
            print(f"数据目录: {data_dir}")
            print(f"目录是否存在: {data_dir.exists()}")
            print(f"目录内容: {list(data_dir.glob('*'))}")
            
            files = [f for f in data_dir.glob('*经纬度*.xlsx')]
            print(f"找到的文件: {files}")
            
            if not files:
                raise FileNotFoundError("未找到经纬度数据文件")
            
            latest_file = sorted(files)[-1]
            print(f"加载数据文件：{latest_file}")
            self.df = pd.read_excel(latest_file)
            
            if '经度' in self.df.columns and '纬度' in self.df.columns:
                for _, row in self.df.iterrows():
                    if pd.notna(row['经度']) and pd.notna(row['纬度']):
                        cache_key = f"{row['城市']}:{row['具体地址']}"
                        self.address_cache[cache_key] = [str(row['经度']), str(row['纬度'])]
        except Exception as e:
            print(f"加载数据出错: {e}")
            raise

    def get_coordinates(self, city, address):
        """获取地址的经纬度"""
        cache_key = f"{city}:{address}"
        if cache_key in self.address_cache:
            return self.address_cache[cache_key]
        
        try:
            url = f"https://restapi.amap.com/v3/geocode/geo"
            params = {
                "key": self.api_key,
                "address": address,
                "city": city
            }
            response = requests.get(url, params=params)
            data = response.json()
            
            if data["status"] == "1" and data["geocodes"]:
                location = data["geocodes"][0]["location"].split(",")
                self.address_cache[cache_key] = location
                return location
        except Exception as e:
            print(f"获取坐标失败: {e}")
        return None
    
    def calculate_distance(self, lat1, lon1, lat2, lon2):
        """计算两点间距离"""
        R = 6371  # 地球半径（公里）
        
        lat1, lon1, lat2, lon2 = map(radians, map(float, [lat1, lon1, lat2, lon2]))
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        distance = R * c
        
        return round(distance, 2)
    
    def get_route_info(self, origin, destination):
        """获取路线信息"""
        route_info = {"driving": {}, "transit": {}}
        
        # 驾车路线
        try:
            url = "https://restapi.amap.com/v3/direction/driving"
            params = {
                "key": self.api_key,
                "origin": origin,
                "destination": destination,
                "extensions": "base"
            }
            response = requests.get(url, params=params)
            data = response.json()
            
            if data["status"] == "1" and data["route"]["paths"]:
                path = data["route"]["paths"][0]
                route_info["driving"] = {
                    "distance": round(float(path["distance"])/1000, 2),
                    "time": round(float(path["duration"])/60),
                    "steps": [step["instruction"] for step in path["steps"]]
                }
        except Exception as e:
            print(f"获取驾车路线失败: {e}")
        
        # 公交路线
        try:
            url = "https://restapi.amap.com/v3/direction/transit/integrated"
            params = {
                "key": self.api_key,
                "origin": origin,
                "destination": destination,
                "city1": "上海",
                "city2": "上海"
            }
            response = requests.get(url, params=params)
            data = response.json()
            
            if data["status"] == "1" and data["route"]["transits"]:
                transit = data["route"]["transits"][0]
                steps = []
                for segment in transit["segments"]:
                    if "walking" in segment:
                        steps.append({
                            "type": "walking",
                            "distance": segment["walking"]["distance"],
                            "duration": round(float(segment["walking"]["duration"])/60)
                        })
                    if "bus" in segment:
                        steps.append({
                            "type": "bus",
                            "name": segment["bus"]["buslines"][0]["name"],
                            "departure": segment["bus"]["buslines"][0]["departure_stop"]["name"],
                            "arrival": segment["bus"]["buslines"][0]["arrival_stop"]["name"],
                            "stops": segment["bus"]["buslines"][0]["via_num"],
                            "duration": round(float(segment["bus"]["buslines"][0]["duration"])/60)
                        })
                
                route_info["transit"] = {
                    "time": round(float(transit["duration"])/60),
                    "steps": steps
                }
        except Exception as e:
            print(f"获取公交路线失败: {e}")
        
        return route_info

    def find_nearby_courses(self, address, district=None, class_type=None, course_type=None, city='上海'):
        """查找附近课程"""
        print(f"开始查询课程")
        print(f"筛选条件: 区域={district}, 班型={class_type}, 课程类型={course_type}")
        
        # 应用筛选条件
        df = self.df[self.df['城市'] == city].copy()
        print(f"同城市课程数量: {len(df)}")
        
        if district:
            df = df[df['行政区'] == district]
        if class_type:
            df = df[df['班型'] == class_type]
        if course_type:
            df = df[df['课程分类'] == course_type]
        
        results = []
        user_coords = None
        
        if address:
            # 获取用户地址的坐标
            user_coords = self.get_coordinates(city, address)
            if not user_coords:
                return {"error": "无法获取地址坐标"}
            
            print(f"用户地址坐标: {user_coords}")
            
            # 计算距离并排序
            distances = []
            for _, row in df.iterrows():
                distance = self.calculate_distance(
                    user_coords[1], user_coords[0],
                    row['纬度'], row['经度']
                )
                distances.append((distance, row))
            
            distances.sort(key=lambda x: x[0])
            df_sorted = pd.DataFrame([item[1] for item in distances[:5]])
            
            if not df_sorted.empty:
                print("开始获取前5个课程的路线信息...")
                for _, row in df_sorted.iterrows():
                    coords = f"{row['经度']},{row['纬度']}"
                    user_coords_str = f"{user_coords[0]},{user_coords[1]}"
                    
                    print(f"开始获取路线信息: {user_coords_str} -> {coords}")
                    route_info = self.get_route_info(user_coords_str, coords)
                    
                    results.append({
                        "课程名称": row['课程'],
                        "地址": row['具体地址'],
                        "距离": self.calculate_distance(
                            user_coords[1], user_coords[0],
                            row['纬度'], row['经度']
                        ),
                        "route_info": route_info
                    })
        else:
            # 不计算距离，直接返回筛选结果
            df_sorted = df.head(20)
            for _, row in df_sorted.iterrows():
                results.append({
                    "课程名称": row['课程'],
                    "地址": row['具体地址']
                })
        
        print(f"找到{len(results)}个符合条件的课程")
        return {"results": results, "user_coords": user_coords}

course_service = CourseService()

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/filters')
def get_filters():
    """获取筛选选项"""
    city = request.args.get('city', '上海')
    return jsonify({
        'districts': sorted(course_service.df[course_service.df['城市'] == city]['行政区'].unique().tolist()),
        'class_types': sorted(course_service.df[course_service.df['城市'] == city]['班型'].unique().tolist()),
        'course_types': sorted(course_service.df[course_service.df['城市'] == city]['课程分类'].unique().tolist())
    })

@app.route('/search', methods=['POST'])
def search():
    """搜索课程"""
    try:
        data = request.json
        city = data.get('city', '上海')
        address = data.get('address', '')
        filters = data.get('filters', {})
        
        print(f"接收到查询请求: city={city}, address={address}, filters={filters}")
        
        results = course_service.find_nearby_courses(
            address,
            district=filters.get('district'),
            class_type=filters.get('class_type'),
            course_type=filters.get('course_type'),
            city=city
        )
        return jsonify(results)
    except Exception as e:
        print(f"查询出错: {str(e)}")
        return jsonify({"error": f"查询出错: {str(e)}"}), 500

# Vercel 处理函数
def handler(request):
    """处理 Vercel 请求"""
    return app 