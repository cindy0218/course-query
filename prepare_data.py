import pandas as pd
import requests
import time
import re

def get_coordinates(address, api_key, city='上海'):
    """获取地址的经纬度"""
    # 确保地址包含城市名
    if not any(prefix in address for prefix in [f'{city}', f'{city}市']):
        address = f"{city}市{address}"
    
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {
        'address': address,
        'key': api_key,
        'city': '上海',
        'output': 'JSON'
    }
    
    try:
        response = requests.get(url, params=params)
        data = response.json()
        
        if data['status'] == '1' and data['geocodes']:
            # 验证返回的地址是否在上海
            formatted_address = data['geocodes'][0]['formatted_address']
            if not formatted_address.startswith('上海市'):
                print(f"警告：地址不在上海: {address} -> {formatted_address}")
                return None, None
                
            location = data['geocodes'][0]['location']
            print(f"成功：{address} -> {formatted_address}")
            return location.split(',')
            
        print(f"无法获取地址坐标: {address} - {data.get('info')}")
        return None, None
    except Exception as e:
        print(f"请求出错: {e}")
        return None, None

def normalize_district(district):
    """统一行政区格式"""
    # 移除"上海"/"上海市"前缀
    district = district.replace('上海', '').replace('市', '')
    
    # 统一浦东新区的写法
    if '浦东' in district:
        return '浦东新区'
    
    # 确保以"区"结尾
    if not district.endswith('区'):
        district += '区'
    
    return district

def normalize_class_type(class_type):
    """统一班型分类"""
    if '私教' in class_type:
        return '私教'
    elif '1人即可' in class_type:
        return '一人即可'
    else:
        return '团课'

def parse_course_info(course_name, address):
    """解析课程信息"""
    # 解析班型
    class_type_match = re.search(r'【(.*?)】', course_name)
    class_type = class_type_match.group(1) if class_type_match else '未知'
    class_type = normalize_class_type(class_type)
    
    # 解析课程类型
    course_type_match = re.search(r'-([^-]*)-\d+节', course_name)
    course_type = course_type_match.group(1) if course_type_match else '未知'
    
    # 从地址中提取区域
    # 先尝试匹配标准格式
    district_match = re.search(r'上海市?(.+?)[区县]', address)
    # 如果没找到，尝试匹配特殊情况（如浦东）
    if not district_match:
        if '浦东' in address:
            district = '浦东新区'
        else:
            district = '未知区'
            print(f"警告：无法从地址中提取区域：{address}")
    else:
        district = district_match.group(1) + '区'
    district = normalize_district(district)
    
    return {
        'class_type': class_type,
        'course_type': course_type,
        'district': district,
    }

def clean_course_name(name):
    """清理课程名称中的emoji等特殊字符"""
    # 使用正则表达式移除emoji和其他特殊字符
    return re.sub(r'[^\u4e00-\u9fff\-a-zA-Z0-9]', '', name)

def generate_course_name(row):
    """生成标准格式的课程名称
    格式：【班型】区域-课程-节数
    示例：【6-8人团】黄浦南京东路-养生锤-8节
    """
    clean_course = clean_course_name(row['原始课程'])
    return f"【{row['班型原始']}】{row['区域']}{row['地铁站']}-{clean_course}-{row['课时']}节"

def prepare_course_data(city='上海'):
    api_key = '674239fafbc08091cf2f2c8bd6fa128a'
    
    # 使用固定的日期
    date_str = '20250111'
    input_file = f'{city}课表汇总_{date_str}.xlsx'
    output_file = f'{city}课表经纬度_{date_str}.xlsx'
    
    # 读取原始数据
    try:
        df = pd.read_excel(input_file)
        # 重命名列以匹配新格式
        df = df.rename(columns={
            '大类': '课程分类',  # 使用大类作为课程分类
            '课程': '原始课程',  # 临时保存原始课程名
            '区': '区域',
            '地铁': '地铁站',
            '上课方式': '班型原始',
            '节数': '课时'
        })
    except FileNotFoundError:
        print(f"错误：找不到文件 {input_file}")
        return
    
    # 生成标准格式的课程名称
    df['课程'] = df.apply(generate_course_name, axis=1)  # 生成标准格式课程名
    
    # 添加城市字段
    df['城市'] = city
    
    # 解析课程信息（保留原有区域信息）
    df['班型'] = df['班型原始'].apply(normalize_class_type)
    df['课程类型'] = df['课程分类']  # 直接使用大类作为课程类型
    df['行政区'] = df['区域'].apply(lambda x: '浦东新区' if '浦东' in x else x + '区')
    
    # 构建完整地址
    df['具体地址'] = df.apply(lambda row: f"{city}市{row['区域']}{row['具体地址']}".replace(row['区域']+row['区域'], row['区域']), axis=1)
    
    # 获取唯一地址列表
    unique_addresses = df['具体地址'].unique()
    print(f"总共有{len(df)}个课程，{len(unique_addresses)}个不同地址")
    
    # 创建地址到坐标的映射
    address_coords = {}
    
    for address in unique_addresses:
        if address not in address_coords:
            print(f"处理地址: {address}")
            lng, lat = get_coordinates(address, api_key)
            if lng and lat:
                address_coords[address] = [lng, lat]
            time.sleep(0.5)  # 控制请求频率
    
    # 更新DataFrame
    df['经度'] = df['具体地址'].map(lambda x: address_coords.get(x, [None, None])[0])
    df['纬度'] = df['具体地址'].map(lambda x: address_coords.get(x, [None, None])[1])
    
    # 保存结果前添加检查
    print("\n未识别区域的地址：")
    unknown_districts = df[df['行政区'] == '未知区']
    if len(unknown_districts) > 0:
        print("\n以下地址未能识别行政区：")
        for _, row in unknown_districts.iterrows():
            print(f"课程：{row['课程']}")
            print(f"地址：{row['具体地址']}\n")
    else:
        print("所有地址都已正确识别行政区")
    
    # 保存结果
    df.to_excel(output_file, index=False)
    print(f"数据处理完成，已保存到：{output_file}")
    
    # 输出统计信息
    print("\n数据统计：")
    print(f"班型：{df['班型'].unique().tolist()}")
    print(f"课程类型：{df['课程类型'].unique().tolist()}")
    print(f"行政区：{df['行政区'].unique().tolist()}")

if __name__ == "__main__":
    prepare_course_data() 