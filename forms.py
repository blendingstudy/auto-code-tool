from flask_wtf import FlaskForm
from wtforms import TextAreaField, SubmitField
from wtforms.validators import DataRequired

class FlowchartForm(FlaskForm):
    flowchart = TextAreaField('Flowchart', validators=[DataRequired()])
    submit = SubmitField('Submit')
