from flask_wtf import FlaskForm
from wtforms import StringField, SelectField, DateField, HiddenField, SubmitField, IntegerField
from wtforms.validators import DataRequired, Optional, Length, Regexp, NumberRange

class WorkLogForm(FlaskForm):
    personid = SelectField(
        '📌 PersonID:', 
        validators=[DataRequired("PersonIDを選択してください。")]
    )
    workcd = StringField(
        '🔍 品番コード:', 
        validators=[
            Optional(), # 品番コードは任意入力とする（品名直接選択の場合もあるため）
            Length(min=3, message="品番コードは3文字以上で入力してください。") 
            # Regexp(r'^[0-9]*$', message="品番コードは半角数字で入力してください。") # 必要であれば数字のみバリデーション追加
        ]
    )
    # workname は JavaScript で動的に内容が変わり、その選択された値(文字列)を受け取る想定
    workname = StringField(
        '📚 品名:',
        validators=[Optional()] # 品番コードを入力した場合に選択必須とするかは、ルート側で追加バリデーションも検討
    )
    bookname_hidden = HiddenField('書名（Hidden）') # JavaScriptが設定する隠しフィールド

    workprocess = SelectField(
        '🛠 行程名:', 
        validators=[DataRequired("行程名を選択してください。")]
    )
    # unitprice はJavaScriptで表示専用のため、WTFormsのフィールドとしては通常含めないか、表示専用とする
    # unitprice = StringField('💰 単価:', render_kw={'readonly': True})

    workoutput = StringField( # IntegerFieldだと空文字でエラーになるため、StringField＋Regexpが良い場合がある
        '📦 数量（個、分）:', 
        validators=[
            DataRequired("数量を入力してください。"),
            Regexp(r'^[1-9][0-9]*$|^0$', message="数量は0以上の半角整数で入力してください。") # 0または正の整数
        ]
    )
    workday = DateField(
        '📅 作業日:', 
        format='%Y-%m-%d', 
        validators=[DataRequired("作業日を選択または入力してください。")]
    )
    submit = SubmitField('送信')

    # 必要に応じて、特定のフィールド間の関連性などをチェックするカスタムバリデータを追加することも可能
    # def validate_workname(self, field):
    #     if self.workcd.data and not field.data:
    #         raise ValidationError('品番コードを入力した場合、品名も選択してください。')