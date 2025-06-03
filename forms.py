# forms.py
from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, DateField, HiddenField, SubmitField
from wtforms.validators import DataRequired, Optional, Length, Regexp # NumberRange は一旦外します

class WorkLogForm(FlaskForm):
    personid = SelectField(
        '📌 PersonID:',
        validators=[DataRequired("PersonIDを選択してください。")]
    )
    workcd = StringField(
        '🔍 品番コード:',
        validators=[
            Optional(),
            Length(min=3, max=20, message="品番コードは3文字以上20桁以内で入力してください。")
            # 必要であれば Regexp(r'^[0-9]*$', message="品番コードは半角数字で入力してください。") など追加
        ]
    )
    workname = StringField( # JavaScriptで動的に選択される品名の値を受け取る
        '📚 品名:',
        validators=[Optional()] # 品番コードが入力された場合に必須とするかは、ルート側で追加検証も可
    )
    bookname_hidden = HiddenField('書名（Hidden）') # JavaScriptが設定する

    workprocess = SelectField(
        '🛠 行程名:',
        validators=[DataRequired("行程名を選択してください。")]
    )
    # unitprice は表示専用なので、WTFormsのフィールドとしては必須ではない
    
    workoutput = StringField( # IntegerFieldだと空文字でバリデーション前にエラーになることがあるためStringFieldで
        '📦 数量（個、分）:',
        validators=[
            DataRequired("数量を入力してください。"),
            Regexp(r'^[0-9]+$', message="数量は0以上の半角整数で入力してください。") # 0以上の整数
        ]
    )
    workday = DateField(
        '📅 作業日:',
        format='%Y-%m-%d',
        validators=[DataRequired("作業日を選択または入力してください。")]
    )
    submit = SubmitField('送信')

    # カスタムバリデーターの例 (必要であれば)
    # def validate_workname(self, field):
    #     if self.workcd.data and not field.data:
    #         from wtforms.validators import StopValidation # or ValidationError
    #         raise StopValidation('品番コードを入力した場合、品名も選択してください。')