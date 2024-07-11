from flask import Flask, render_template, request, redirect, url_for, flash
from forms import FlowchartForm
from utils import generate_code
from ai_models import gpt_request, AiType

app = Flask(__name__)
app.config.from_object('config.Config')

@app.route('/', methods=['GET', 'POST'])
def index():
    form = FlowchartForm()
    if form.validate_on_submit():
        flowchart = form.flowchart.data
        functions, call_order = generate_code(flowchart)
        return render_template('functions.html', functions=functions, call_order=call_order)
    return render_template('index.html', form=form)

@app.route('/generate', methods=['POST'])
def generate():
    # 사용자 확인 후 코드 생성 및 파일 저장
    # ...
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
