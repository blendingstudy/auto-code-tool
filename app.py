import json
import os
import re
import sys
import threading
import subprocess
import shlex
import time
from flask import Flask, render_template, request, jsonify
from config import Config
from ai_models import gpt_request_with_retry

app = Flask(__name__)
app.config.from_object(Config)

# Global variables for account and project GUIDs
account_guid = ''
project_guid = ''


def validate_flowchart(project_description, flowchart):
    if not project_description.strip():
        return False, "프로젝트 설명을 입력해주세요."
    if not flowchart.strip():
        return False, "플로우차트를 입력해주세요."
    return True, ""


def construct_prompt(project_description, flowchart, is_new_project, has_been_requested_before):
    if is_new_project or not has_been_requested_before:
        initial_prompt = project_description + "\n\n\n" + flowchart
    else:
        initial_prompt = flowchart
    prompt = initial_prompt + """
    \n\n\n
    위의 내용을 토대로 각 기능별로 필요한 함수들을 나누고, 각 함수의 파라미터와 자료형까지 자세히 포함한 함수 호출표를 만들어줘.
    각 기능별로 함수가 나뉘어지고 각 함수의 파라미터와 자료형까지 명확히 기술된 형태로 작성해줘.
    답변은 json으로만 해줘. 파싱하기 위함이라 다른걸로 하면 안돼.
    예시:
    {
        "1": {
            "title": "사용자 인증 및 회원 관리",
            "functions": [
                {
                    "name": "auth_controller.register",
                    "description": "회원가입 처리",
                    "parameters": [
                        {"name": "username", "type": "string"},
                        {"name": "email", "type": "string"},
                        {"name": "password", "type": "string"}
                    ]
                },
                {
                    "name": "auth_controller.login",
                    "description": "로그인 처리",
                    "parameters": [
                        {"name": "email", "type": "string"},
                        {"name": "password", "type": "string"}
                    ]
                }
                // 다른 함수들...
            ]
        },
        "2": {
            "title": "상품 관리",
            "functions": [
                {
                    "name": "product_controller.create_product",
                    "description": "새로운 상품 생성",
                    "parameters": [
                        {"name": "name", "type": "string"},
                        {"name": "description", "type": "string"},
                        {"name": "price", "type": "float"},
                        {"name": "quantity", "type": "int"}
                    ]
                }
                // 다른 함수들...
            ]
        }
        // 다른 기능들...
    }
    """
    return prompt


def construct_api_prompt(project_description, function_call_chart):
    prompt = f"{project_description}\n\n{function_call_chart}\n\n"
    prompt += """
    위의 설명과 함수 호출표를 기반으로 필요한 API 목록을 작성해줘.
    각 API의 엔드포인트와 필요한 파라미터를 포함해줘.
    메인 엔드포인트 '/'도 포함해야 해.
    답변은 json 형식으로만 해줘. 예시는 다음과 같아야 해:
    {
        "api": [
            {
                "endpoint": "/",
                "description": "메인 페이지",
                "parameters": []
            },
            {
                "endpoint": "/api/register",
                "description": "회원가입 처리",
                "parameters": [
                    {"name": "username", "type": "string"},
                    {"name": "email", "type": "string"},
                    {"name": "password", "type": "string"}
                ]
            }
            // 다른 API들...
        ]
    }
    """
    return prompt


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


@app.route('/generate_code', methods=['POST'])
def generate_code():
    global account_guid, project_guid

    data = request.get_json()
    account_guid = data['account_guid']
    project_guid = data['project_guid']
    project_description = data['project_description']
    flowchart = data['flowchart']

    is_valid, error_message = validate_flowchart(project_description, flowchart)
    if not is_valid:
        return jsonify({'error': error_message}), 400

    path = f'code/{account_guid}/{project_guid}/project_data.json'
    if os.path.exists(path):
        with open(path, 'r') as f:
            project_data = json.load(f)
            existing_description = project_data['project_description']
            is_new_project = False
            has_been_requested_before = 'gpt_request' in project_data
    else:
        existing_description = ""
        is_new_project = True
        has_been_requested_before = False

    if existing_description != project_description:
        is_new_project = True

    constructed_prompt = construct_prompt(
        project_description,
        flowchart,
        is_new_project,
        has_been_requested_before
    )

    response = gpt_request_with_retry(constructed_prompt)
    project_data = {
        'account_guid': account_guid,
        'project_guid': project_guid,
        'project_description': project_description,
        'flowchart': flowchart,
        'gpt_request': response
    }
    save_project_data(project_data)
    formatted_response = format_response(response)
    save_function_call_chart(formatted_response)

    return jsonify({'formatted_response': formatted_response})


@app.route('/modify_function_call_chart', methods=['POST'])
def modify_function_call_chart():
    global account_guid, project_guid

    data = request.get_json()
    account_guid = data['account_guid']
    project_guid = data['project_guid']
    modification_prompt = data['modification_prompt']

    path = f'code/{account_guid}/{project_guid}/project_data.json'
    if not os.path.exists(path):
        return jsonify({'error': '프로젝트를 찾을 수 없습니다.'}), 404

    with open(path, 'r') as f:
        project_data = json.load(f)

    existing_chart = project_data.get('gpt_request', "")
    constructed_prompt = existing_chart + "\n\n" + modification_prompt
    constructed_prompt += "답변은 json으로만 해줘. 파싱하기 위함이라 다른걸로 하면 안돼."

    response = gpt_request_with_retry(constructed_prompt)
    print(response)
    try:
        formatted_response = format_response(response)
    except json.JSONDecodeError as e:
        return jsonify({'error': '응답을 JSON으로 파싱하는데 실패했습니다.', 'details': str(e)}), 500

    # 수정된 Flowchart를 project_data에 업데이트하여 저장
    project_data['flowchart'] = modification_prompt
    project_data['gpt_request'] = response
    save_project_data(project_data)  # 프로젝트 데이터를 저장

    save_function_call_chart(formatted_response)

    return jsonify({'formatted_response': formatted_response})



@app.route('/generate_project_code', methods=['POST'])
def generate_project_code():
    global account_guid, project_guid

    data = request.get_json()
    account_guid = data['account_guid']
    project_guid = data['project_guid']

    path = f'code/{account_guid}/{project_guid}/project_data.json'
    function_call_path = f'code/{account_guid}/{project_guid}/function_call_chart.txt'
    if not os.path.exists(path):
        return jsonify({'error': 'Project not found'}), 404
    if not os.path.exists(function_call_path):
        return jsonify({'error': 'function call chart not found'}), 404

    with open(path, 'r') as f:
        project_data = json.load(f)
        project_description = project_data['project_description']
        flowchart = project_data['flowchart']

    with open(function_call_path, 'r') as f:
        function_call_chart_content = f.read()

    prompt = f"{project_description}\n\n{flowchart}\n\n{function_call_chart_content}\n\n"
    prompt += """
    위에 적어 놓은 설명, flow chart 그리고 함수 호출표를 이용해서 즉시 실행 할 수 있는 프로젝트를 만들거야. python flask 와 html로 만들어줘.
    이 프로젝트를 설계하고 코드파일리스트를 만들어줘. flask는 app.py와 requirements.txt가 반드시 필요해.
    HTML 파일은 index.html로 만들고, 모든 JavaScript 코드를 그 안에 포함시켜줘. app폴더 안에 있도록 해줘
    각 함수 이름이 일치하도록 주의해서 작성해줘.
    답변은 json으로만 해줘. 파싱하기 위함이라 다른걸로 하면 안돼.
    json에 기획 요약내용도 포함되어 있어야해.
    코드구현은 하지마, 설계파일 리스트만 제공하면 돼.
    path에는 file 이름이 들어가 있으면 안돼.
    코드파일이면 functionList:[]가 포함되어야 하고
    리소스파일이면 functionList는 없어도 돼.
    객체파일이면 objectName도 있어야해.
    객체가 아니면 NoneObject라고 필드값 주면돼.

    {
        plan: ... ,
        Files:[
            {path,fname,objectName,functionList:["functionName(args)",]},
            {path,fname},
        ]
    }
    """

    response = gpt_request_with_retry(prompt)
    print(response)
    code_structure = parse_code_structure(response)
    save_code_structure(code_structure)

    # API 목록 생성
    # api_prompt = construct_api_prompt(project_description, function_call_chart)
    # api_response = gpt_request_with_retry(api_prompt)
    # api_list = parse_code_structure(api_response)
    # save_api_list(api_list)

    files = code_structure.get('Files', [])
    threads = []

    for file_info in files:
        # t = threading.Thread(target=implement_file, args=(file_info, code_structure, api_list))
        t = threading.Thread(target=implement_file, args=(file_info, code_structure))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    return jsonify(code_structure)


@app.route('/update_project_code', methods=['POST'])
def update_project_code():
    global account_guid, project_guid

    data = request.get_json()
    account_guid = data['account_guid']
    project_guid = data['project_guid']

    project_data_path = f'code/{account_guid}/{project_guid}/project_data.json'
    code_structure_path = f'code/{account_guid}/{project_guid}/code_structure.json'

    if not os.path.exists(project_data_path) or not os.path.exists(code_structure_path):
        return jsonify({'error': '프로젝트를 찾을 수 없습니다.'}), 404

    with open(project_data_path, 'r') as f:
        project_data = json.load(f)
        project_description = project_data['project_description']
        flowchart = project_data['flowchart']
        function_call_chart = project_data['gpt_request']

    with open(code_structure_path, 'r') as f:
        code_structure = json.load(f)

    prompt = f"{project_description}\n\n{flowchart}\n\n{function_call_chart}\n\n"
    prompt += "위에 적어 놓은 설명과 수정된 flow chart를 이용해서 기존 코드를 최대한 유지하면서 새로운 기능만 추가해줘. 기존 기능은 수정하지 말고, 새로운 기능만 반영할 수 있도록 코드를 수정해줘. 답변은 json으로만 해줘. 파싱하기 위함이라 다른걸로 하면 안돼."

    # 선택한 파일들의 내용을 포함
    prompt += "기존 파일들의 내용:\n"
    for file_info in code_structure['Files']:
        file_path = f'code/{account_guid}/{project_guid}/{file_info["path"]}/{file_info["fname"]}'
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                file_content = f.read()
            prompt += f"파일: {file_info['fname']} 내용:\n{file_content}\n\n"

    prompt += "위 파일들을 수정하여 새로운 코드를 생성해주세요. JSON 형식으로만 응답해줘."

    response = gpt_request_with_retry(prompt)
    print(response)
    try:
        if response.strip().startswith("```json"):
            response = response.strip()[7:-3].strip()
        if not response:
            return jsonify({'error': '빈 JSON 응답입니다.'}), 500
        response_json = json.loads(response)
    except json.JSONDecodeError as e:
        return jsonify({'error': '응답을 JSON으로 파싱하는데 실패했습니다.', 'details': str(e)}), 500

    # 파일 저장 로직 수정
    for fname, file_info in response_json.items():
        # code_structure에서 해당 파일의 경로를 찾음
        path = ''
        for file in code_structure['Files']:
            if file['fname'] == fname:
                path = file.get('path', '')
                break

        # file_info가 문자열인지 확인하고, content가 문자열이면 그대로 사용
        if isinstance(file_info, dict):
            content = file_info.get('content', '')
        else:
            content = file_info  # file_info가 문자열일 경우 그대로 content로 사용

        save_file(path, fname, content)

    return jsonify({'status': 'success', 'files': response_json})


def save_modified_files(modified_files):
    global account_guid, project_guid

    for file_info in modified_files.get('modified_files', []):
        path = file_info['path']
        content = file_info['content']
        file_path = f'code/{account_guid}/{project_guid}/{path}'
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w') as file:
            file.write(content)


@app.route('/load_project', methods=['POST'])
def load_project():
    global account_guid, project_guid

    data = request.get_json()
    account_guid = data['account_guid']
    project_guid = data['project_guid']

    path = f'code/{account_guid}/{project_guid}/project_data.json'
    if os.path.exists(path):
        with open(path, 'r') as f:
            project_data = json.load(f)
        function_call_chart = load_function_call_chart()
        files = load_file_list(account_guid, project_guid)
        return jsonify(
            {"exists": True, "project_data": project_data, "function_call_chart": function_call_chart, "files": files})
    else:
        return jsonify({"exists": False})


@app.route('/get_file_code', methods=['POST'])
def get_file_code():
    global account_guid, project_guid

    file_info = request.get_json()
    path = file_info.get('path', '')
    fname = file_info.get('fname', '')

    file_path = f'code/{account_guid}/{project_guid}/{path}/{fname}'
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            code = file.read()
        return jsonify({"code": code})
    else:
        return jsonify({"code": "파일을 찾을 수 없습니다."}), 404


@app.route('/save_file_code', methods=['POST'])
def save_file_code():
    global account_guid, project_guid

    data = request.get_json()
    path = data.get('path', '')
    fname = data.get('fname', '')
    code = data.get('code', '')

    file_path = f'code/{account_guid}/{project_guid}/{path}/{fname}'
    with open(file_path, 'w') as file:
        file.write(code)
    return jsonify({"status": "success"})


def load_file_list(account_guid, project_guid):
    path = f'code/{account_guid}/{project_guid}'
    excluded_files = {'function_call_chart.txt', 'code_structure.json', 'project_data.json'}
    file_list = []
    for root, dirs, files in os.walk(path):
        for file in files:
            if file not in excluded_files:
                file_info = {
                    'path': os.path.relpath(root, path),
                    'fname': file
                }
                file_list.append(file_info)
    return file_list


def parse_code_structure(response):
    response = response.strip()
    print(f"Response: {response}")
    if response.startswith('{'):
        try:
            code_structure = json.loads(response)
            return code_structure
        except json.JSONDecodeError as e:
            print(f"JSON decode error: {e}")
            return {}
    else:
        json_match = re.search(r'```json(.*?)```', response, re.DOTALL)
        if json_match:
            json_content = json_match.group(1).strip()
            print(json_content)
            try:
                code_structure = json.loads(json_content)
                return code_structure
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}")
                return {}
        else:
            print("No JSON content found.")
            return {}
    return {}


def save_code_structure(code_structure):
    global account_guid, project_guid

    path = f'code/{account_guid}/{project_guid}'
    os.makedirs(path, exist_ok=True)
    with open(f'{path}/code_structure.json', 'w') as f:
        json.dump(code_structure, f, ensure_ascii=False, indent=4)


def save_api_list(api_list):
    global account_guid, project_guid

    path = f'code/{account_guid}/{project_guid}'
    os.makedirs(path, exist_ok=True)
    with open(f'{path}/api_list.json', 'w') as f:
        json.dump(api_list, f, ensure_ascii=False, indent=4)


def implement_file(file_info, full_code_structure):
    global account_guid, project_guid

    path = file_info.get('path', '')
    fname = file_info.get('fname', '')
    object_name = file_info.get('objectName', '')
    function_list = file_info.get('functionList', [])

    print(f"Implementing file: {fname}, object_name: {object_name}")
    print(f"Function list: {function_list}")

    # 이전에 생성된 파일들의 내용을 읽어옴
    previous_files_content = ""
    base_path = f'code/{account_guid}/{project_guid}/{path}'
    if os.path.exists(base_path):
        for root, dirs, files in os.walk(base_path):
            for file in files:
                if file != fname:  # 현재 생성 중인 파일은 제외
                    with open(os.path.join(root, file), 'r') as f:
                        file_content = f.read()
                        previous_files_content += f"\n\n# {file} 내용:\n{file_content}\n"

    prompt = f"Based on the following code structure and previous file contents, implement the functions for the file {fname}:\n\n"
    prompt += json.dumps(full_code_structure, indent=2)
    prompt += "\n\nConsidering the relationship with other files, make it immediately viable\n"
    prompt += "\n\nPlease pay attention to the import and function name when you create the code\n"
    prompt += "\n\nDo not use files that are not in code structure. For example, do not use html files with different names\n"

    prompt += f"\n\nImplement the following functions for {object_name}:\n"
    # prompt += f"\n\nPrevious files content:\n{previous_files_content}\n"
    # prompt += f"\n\nAPI list:\n{json.dumps(api_list, indent=2)}\n"

    if function_list:
        for function in function_list:
            if isinstance(function, dict):
                if 'parameters' in function:
                    if isinstance(function['parameters'], str):
                        try:
                            function['parameters'] = json.loads(function['parameters'])
                        except json.JSONDecodeError:
                            print(f"Error parsing parameters for function {function['name']}: {function['parameters']}")
                            function['parameters'] = []

                    if isinstance(function['parameters'], list):
                        parameters = ', '.join(['{}: {}'.format(p['name'], p['type']) for p in function['parameters']])
                        prompt += f"- {function['name']}({parameters})\n"
                    else:
                        prompt += f"- {function['name']}()\n"
                else:
                    prompt += f"- {function.get('name', 'unknown_function')}()\n"
            elif isinstance(function, str):
                prompt += f"- {function}()\n"
            else:
                print(f"Invalid function format: {function}")
    else:
        prompt += "No specific functions provided."

    response = gpt_request_with_retry(prompt)

    code_match = re.search(r'```(?:.|\n)*?\n(.*?)```', response, re.DOTALL)
    if code_match:
        file_content = code_match.group(1).strip()
    else:
        file_content = response

    save_file(path, fname, file_content)


# @app.route('/modify_code', methods=['POST'])
# def modify_code():
#     global account_guid, project_guid
#
#     data = request.get_json()
#     account_guid = data['account_guid']
#     project_guid = data['project_guid']
#     code_modification_prompt = data['code_modification_prompt']
#     selected_files = data['selected_files']
#
#     project_data_path = f'code/{account_guid}/{project_guid}/project_data.json'
#     code_structure_path = f'code/{account_guid}/{project_guid}/code_structure.json'
#
#     if not os.path.exists(project_data_path) or not os.path.exists(code_structure_path):
#         return jsonify({'error': '프로젝트를 찾을 수 없습니다.'}), 404
#
#     with open(project_data_path, 'r') as f:
#         project_data = json.load(f)
#         project_description = project_data['project_description']
#         flowchart = project_data['flowchart']
#         function_call_chart = project_data['gpt_request']
#
#     with open(code_structure_path, 'r') as f:
#         code_structure = json.load(f)
#
#     prompt = f"{project_description}\n\n{flowchart}\n\n{function_call_chart}\n\n"
#     prompt += "위에 적어 놓은 설명, flow chart 그리고 함수 호출표를 이용해서 내가 앞으로 주는 코드들을 수정해줘."
#     prompt += f"수정 요청: {code_modification_prompt}\n\n"
#
#     # 선택한 파일들의 내용을 포함
#     prompt += "수정할 파일들의 내용:\n"
#     for file_info in selected_files:
#         file_path = f'code/{account_guid}/{project_guid}/{file_info["path"]}/{file_info["fname"]}'
#         if os.path.exists(file_path):
#             with open(file_path, 'r') as f:
#                 file_content = f.read()
#             prompt += f"파일: {file_info['fname']} 내용:\n{file_content}\n\n"
#
#     prompt += "위 파일들을 수정하여 새로운 코드를 생성해주세요. JSON 형식으로만 응답해줘."
#
#     response = gpt_request_with_retry(prompt)
#     print(response)
#     try:
#         if response.strip().startswith("```json"):
#             response = response.strip()[7:-3].strip()
#         if not response:
#             return jsonify({'error': '빈 JSON 응답입니다.'}), 500
#         response_json = json.loads(response)
#     except json.JSONDecodeError as e:
#         return jsonify({'error': '응답을 JSON으로 파싱하는데 실패했습니다.', 'details': str(e)}), 500
#
#     # 파일 저장 로직 수정
#     for fname, file_info in response_json.items():
#         # code_structure에서 해당 파일의 경로를 찾음
#         path = ''
#         for file in code_structure['Files']:
#             if file['fname'] == fname:
#                 path = file.get('path', '')
#                 break
#
#         # file_info가 문자열인지 확인하고, content가 문자열이면 그대로 사용
#         if isinstance(file_info, dict):
#             content = file_info.get('content', '')
#         else:
#             content = file_info  # file_info가 문자열일 경우 그대로 content로 사용
#
#         save_file(path, fname, content)
#
#     return jsonify({'status': 'success', 'files': response_json})

@app.route('/modify_code', methods=['POST'])
def modify_code():
    global account_guid, project_guid

    data = request.get_json()
    account_guid = data['account_guid']
    project_guid = data['project_guid']
    code_modification_prompt = data['code_modification_prompt']
    selected_files = data['selected_files']

    project_data_path = f'code/{account_guid}/{project_guid}/project_data.json'
    code_structure_path = f'code/{account_guid}/{project_guid}/code_structure.json'

    if not os.path.exists(project_data_path) or not os.path.exists(code_structure_path):
        return jsonify({'error': '프로젝트를 찾을 수 없습니다.'}), 404

    with open(project_data_path, 'r') as f:
        project_data = json.load(f)
        project_description = project_data['project_description']
        flowchart = project_data['flowchart']
        function_call_chart = project_data['gpt_request']

    with open(code_structure_path, 'r') as f:
        code_structure = json.load(f)

    prompt = f"{project_description}\n\n{flowchart}\n\n{function_call_chart}\n\n"
    prompt += "위에 적어 놓은 설명, flow chart 그리고 함수 호출표를 이용해서 내가 앞으로 주는 코드들을 수정해줘."
    prompt += f"수정 요청: {code_modification_prompt}\n\n"

    # 선택한 파일들의 내용을 포함
    prompt += "수정할 파일들의 내용:\n"
    for file_info in selected_files:
        file_path = f'code/{account_guid}/{project_guid}/{file_info["path"]}/{file_info["fname"]}'
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                file_content = f.read()
            prompt += f"파일: {file_info['fname']} 내용:\n{file_content}\n\n"

    prompt += "위 파일들을 수정하여 새로운 코드를 생성해주세요. JSON 형식으로만 응답해줘."

    response = gpt_request_with_retry(prompt)
    print(response)
    try:
        if response.strip().startswith("```json"):
            response = response.strip()[7:-3].strip()
        if not response:
            return jsonify({'error': '빈 JSON 응답입니다.'}), 500
        response_json = json.loads(response)
    except json.JSONDecodeError as e:
        return jsonify({'error': '응답을 JSON으로 파싱하는데 실패했습니다.', 'details': str(e)}), 500

    # 파일 저장 로직 수정
    for fname, file_info in response_json.items():
        # code_structure에서 해당 파일의 경로를 찾음
        path = ''
        for file in code_structure['Files']:
            if file['fname'] == fname:
                path = file.get('path', '')
                break

        # file_info가 문자열인지 확인하고, content가 문자열이면 그대로 사용
        if isinstance(file_info, dict):
            content = file_info.get('content', '')
        else:
            content = file_info  # file_info가 문자열일 경우 그대로 content로 사용

        save_file(path, fname, content)

    return jsonify({'status': 'success', 'files': response_json})


@app.route('/get_flowchart', methods=['POST'])
def get_flowchart():
    global account_guid, project_guid

    data = request.get_json()
    account_guid = data['account_guid']
    project_guid = data['project_guid']

    project_data_path = f'code/{account_guid}/{project_guid}/project_data.json'

    if not os.path.exists(project_data_path):
        return jsonify({'error': '프로젝트를 찾을 수 없습니다.'}), 404

    with open(project_data_path, 'r') as f:
        project_data = json.load(f)
        flowchart = project_data.get('flowchart', '')

    return jsonify({'flowchart': flowchart})

@app.route('/add_feature', methods=['POST'])
def add_feature():
    global account_guid, project_guid

    data = request.get_json()
    account_guid = data['account_guid']
    project_guid = data['project_guid']
    new_feature_description = data['new_feature_description']

    project_data_path = f'code/{account_guid}/{project_guid}/project_data.json'
    code_structure_path = f'code/{account_guid}/{project_guid}/code_structure.json'

    if not os.path.exists(project_data_path) or not os.path.exists(code_structure_path):
        return jsonify({'error': '프로젝트를 찾을 수 없습니다.'}), 404

    with open(project_data_path, 'r') as f:
        project_data = json.load(f)
        project_description = project_data['project_description']
        flowchart = project_data['flowchart']
        function_call_chart = project_data['gpt_request']

    with open(code_structure_path, 'r') as f:
        code_structure = json.load(f)

    # 기존 플로우차트와 기능 호출표에 새로운 기능을 추가하는 프롬프트 생성
    prompt = f"{project_description}\n\n{flowchart}\n\n{function_call_chart}\n\n"
    prompt += "위에 적어 놓은 설명, flow chart 그리고 함수 호출표를 이용해서 새로운 기능을 추가해줘."
    prompt += f"새로운 기능: {new_feature_description}\n\n"
    prompt += "기존 기능을 유지하며 새로운 기능을 추가할 수 있도록 코드를 수정하고, JSON 형식으로만 응답해줘."

    response = gpt_request_with_retry(prompt)
    print(response)
    try:
        if response.strip().startswith("```json"):
            response = response.strip()[7:-3].strip()
        if not response:
            return jsonify({'error': '빈 JSON 응답입니다.'}), 500
        response_json = json.loads(response)
    except json.JSONDecodeError as e:
        return jsonify({'error': '응답을 JSON으로 파싱하는데 실패했습니다.', 'details': str(e)}), 500

    # 파일 저장 로직 수정
    for fname, file_info in response_json.items():
        # code_structure에서 해당 파일의 경로를 찾음
        path = ''
        for file in code_structure['Files']:
            if file['fname'] == fname:
                path = file.get('path', '')
                break

        if isinstance(file_info, dict):
            content = file_info.get('content', '')
        else:
            content = file_info

        save_file(path, fname, content)

    return jsonify({'status': 'success', 'files': response_json})



# Flask 프로젝트 실행 엔드포인트 추가
@app.route('/run_project', methods=['POST'])
def run_project():
    global account_guid, project_guid

    data = request.get_json()
    account_guid = data['account_guid']
    project_guid = data['project_guid']

    project_path = f'code/{account_guid}/{project_guid}/app'

    if not os.path.exists(project_path):
        return jsonify({'error': 'app 폴더를 찾을 수 없습니다.'}), 404

    # 포트 5001이 이미 사용 중인지 확인하고, 사용 중인 경우 프로세스를 종료합니다.
    try:
        # 포트가 사용 중인지 확인하는 명령
        command_check = 'lsof -i :5001'
        process_check = subprocess.Popen(shlex.split(command_check), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process_check.communicate()

        # 포트가 사용 중일 때, 결과를 분석하여 해당 프로세스를 종료
        if stdout:
            # lsof 결과에서 PID를 추출하여 프로세스를 종료
            for line in stdout.decode().splitlines():
                if "LISTEN" in line:
                    parts = line.split()
                    pid = parts[1]  # PID는 두 번째 열에 있습니다.
                    subprocess.call(['kill', '-9', pid])
                    time.sleep(1)  # 프로세스 종료 대기 시간

        # Flask 서버를 subprocess로 실행
        env = os.environ.copy()
        env["FLASK_APP"] = "app.py"
        command = 'flask run --host=0.0.0.0 --port=5001'

        process = subprocess.Popen(
            shlex.split(command),
            cwd=project_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=1,
            universal_newlines=True
        )

        # 서버가 실행될 시간을 줌
        time.sleep(5)

        # 서버가 정상적으로 실행되었는지 확인하고, 결과 반환
        if process.poll() is None:
            return jsonify({'url': 'http://localhost:5001/'})
        else:
            # 오류가 발생한 경우, 로그를 전송
            stdout, stderr = process.communicate(timeout=5)
            error_logs = stdout.splitlines() + stderr.splitlines()
            return jsonify({'error': 'Flask 서버 실행에 실패했습니다.', 'logs': error_logs}), 500

    except subprocess.TimeoutExpired:
        process.kill()
        return jsonify({'error': 'Flask 서버 실행 시간이 초과되었습니다.'}), 500
    except Exception as e:
        return jsonify({'error': f'Flask 서버 실행 중 오류: {str(e)}'}), 500



def save_file(path, fname, content):
    global account_guid, project_guid

    full_path = f'code/{account_guid}/{project_guid}/{path}'
    os.makedirs(full_path, exist_ok=True)
    with open(f'{full_path}/{fname}', 'w') as f:
        f.write(content)


def format_response(response):
    formatted_response = ""
    try:
        if response.strip().startswith("```json"):
            response = response.strip()[7:-3].strip()
        if not response:
            return '빈 JSON 응답입니다.'
        print(response)
        response_json = json.loads(response)
        for key, value in response_json.items():
            formatted_response += f"{key}. {value['title']}\n"
            for func in value['functions']:
                parameters = ', '.join(['{}: {}'.format(p['name'], p['type']) for p in func['parameters']])
                formatted_response += f"    - {func['name']}({parameters}): {func['description']}\n"
    except Exception as e:
        return f'오류: {str(e)}'
    return formatted_response


def save_function_call_chart(chart):
    global account_guid, project_guid

    path = f'code/{account_guid}/{project_guid}'
    os.makedirs(path, exist_ok=True)
    with open(f'{path}/function_call_chart.txt', 'w') as f:
        f.write(chart)


def load_function_call_chart():
    global account_guid, project_guid

    path = f'code/{account_guid}/{project_guid}/function_call_chart.txt'
    if os.path.exists(path):
        with open(path, 'r') as f:
            return f.read()
    return ""


def save_project_data(project_data):
    global account_guid, project_guid

    path = f'code/{account_guid}/{project_guid}'
    os.makedirs(path, exist_ok=True)
    with open(f'{path}/project_data.json', 'w') as f:
        json.dump(project_data, f)


if __name__ == '__main__':
    app.run(debug=True)
