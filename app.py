from flask import Flask, render_template, request, jsonify, redirect, url_for, flash

from ai_models import gpt_request
from config import Config
import os
import json

app = Flask(__name__)
app.config.from_object(Config)


def validate_flowchart(project_description, flowchart):
    if not project_description.strip():
        return False, "Project description cannot be empty."
    if not flowchart.strip():
        return False, "Flowchart cannot be empty."
    return True, ""


def construct_prompt(project_description, flowchart, is_new_project, has_been_requested_before):
    if is_new_project or not has_been_requested_before:
        initial_prompt = project_description + "\n\n\n" + flowchart
    else:
        initial_prompt = flowchart
    prompt = initial_prompt + """
    \n\n\n
    위의 내용을 토대로 함수호출순서표를 만들어줘.
    함수호출순서표만 가지고도 프로그램을 만들수 있을 정도로 자세히 만들어줘.
    답변은 json으로만 해줘. 파싱하기 위함이라 다른걸로 하면 안돼.
    코드구현은 하지마, 함수호출표만 제공하면 돼.
    """
    return prompt


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


@app.route('/generate_code', methods=['POST'])
def generate_code():
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

    response = gpt_request(constructed_prompt)
    project_data = {
        'account_guid': account_guid,
        'project_guid': project_guid,
        'project_description': project_description,
        'flowchart': flowchart,
        'gpt_request': response
    }
    save_project_data(account_guid, project_guid, project_data)

    return jsonify(response)


@app.route('/load_project', methods=['POST'])
def load_project():
    data = request.get_json()
    account_guid = data['account_guid']
    project_guid = data['project_guid']

    path = f'code/{account_guid}/{project_guid}/project_data.json'
    if os.path.exists(path):
        with open(path, 'r') as f:
            project_data = json.load(f)
        return jsonify({"exists": True, "project_data": project_data})
    else:
        return jsonify({"exists": False})


def save_project_data(account_guid, project_guid, project_data):
    path = f'code/{account_guid}/{project_guid}'
    os.makedirs(path, exist_ok=True)
    with open(f'{path}/project_data.json', 'w') as f:
        json.dump(project_data, f)


if __name__ == '__main__':
    app.run(debug=True)
