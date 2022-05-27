from pywebio import start_server, session, config
from pywebio.input import *
from pywebio.output import *
from pywebio.pin import *
import pandas as pd


config(description='ScanWorder', theme='dark')

# for pandas debugging
pd.set_option('display.max_rows', 2500)
pd.set_option('display.max_columns', 100)
pd.set_option('display.width', 1000)
pd.options.mode.chained_assignment = None

			
class WordScanner:
	
	def __init__(self):
		self.dictionary_df = self.read_from_file
	
	@property
	def read_from_file(self):
		dict_csv_path = 'Dict.csv'
		dict_dataframe = pd.read_csv(filepath_or_buffer=dict_csv_path, sep='\t')
		return dict_dataframe
	
	def find_by_mask(self, mask_, prohibited_common='', prohibited_positions='', required_=''):
		mask_prohibited_list = '^'
		tmp_mask_prohibited_list = ''
		required = list(x for x in required_)
		prohibited_pos_list = str(prohibited_positions).split(';')
		
		# formatting mask
		if isinstance(prohibited_pos_list, str):
			prohibited_pos_list = [prohibited_pos_list]
		
		for i in range(0, len(mask_)):
			if mask_[i] == '-':
				tmp_mask_prohibited_list = f"[^{prohibited_common}"
				for ii in range(0, len(prohibited_pos_list)):
					tmp_separate = prohibited_pos_list[ii].split(sep=":")
					if len(tmp_separate) < 2:
						continue
					if int(tmp_separate[0])-1 == i:
						tmp_mask_prohibited_list += tmp_separate[1]
					else:
						continue
				tmp_mask_prohibited_list += "]"
				if tmp_mask_prohibited_list == "[^]":
					tmp_mask_prohibited_list = "[a-я]"
				mask_prohibited_list += tmp_mask_prohibited_list
			else:
				mask_prohibited_list += f"{mask_[i]}"
		mask_prohibited_list += "$"
		
		# preparing result
		result = self.dictionary_df[self.dictionary_df['Lemma'].str.match(mask_prohibited_list)]
		result = result.loc[result['PoS'] == 's']  # only property
		result = result.sort_values(by=['Freq(ipm)'], ascending=False)  # sort by frequency
		result = result.drop_duplicates(subset='Lemma', keep='first', inplace=False, ignore_index=False)
		
		# filtering by required letters (finally)
		for i in range(0, len(required)):
			result = result[result['Lemma'].str.contains(required[i])]

		return result
		
		
class MainProgram(WordScanner):
	
	def __init__(self):
		WordScanner.__init__(self)
		self.mask = '-----'
		self.required = ''
		self.prohibited_common = ''
		self.prohibited_positions = ''
		self.mp_scope = 'main_window'
		self.result = None
		
	def click_ok(self):
		# refresh variables
		self.mask = str(pin.word).lower()
		self.required = '' + str(pin.required_).lower()
		self.prohibited_common = str(pin.prohibited_common).lower()
		self.prohibited_positions = str(pin.prohibited_positions).lower()
		
		# check proper input
		if self.mask == '':
			toast('Не введена маска')
			return
		if len(self.mask) > 24:
			toast('максимальная длина слова в словаре: 24 символа!')
			self.mask = self.mask[:24]

		# activate search
		with use_scope('word_info', clear=True):
			put_loading(shape='grow', scope='word_info')
		self.result = self.find_by_mask(mask_=self.mask, required_=self.required, prohibited_common=self.prohibited_common, prohibited_positions=self.prohibited_positions)
		self.result[' '] = '\t'*16
		clear('word_info')

		# check result
		if len(self.result.values) == 0:
			toast('ничего не найдено', color='error')
			return
		
		if len(self.result.values) > 1000:
			toast('найдено больше 1000 слов', color='error')
			return
		
		# result OK,  preparing data
		headers = [self.result.keys().values.tolist()]
		table_data = self.result.values.tolist()
		table = headers + table_data

		# output data to browser
		with use_scope('result', clear=True, create_scope=True):

			put_text('\n', scope='result')  # make a gap between main window and result window

			put_scope(
				'tmp_res'
			).style(
				f'border: 0px solid; '
				f'width: 100%; '
				f'padding: 10px; '
				f'border-radius: 10px; '
				f'margin: 0 0; '
				f'background: url("http://pinsknews.by/wp-content/uploads/2021/05/%D0%A1%D0%BA%D0%B0%D0%BD%D0%B2%D0%BE%D1%80%D0%B4.jpg");'
			)

			put_text(
				f"найдено слов: {len(self.result['Lemma'].values)}",
				scope='tmp_res'
			).style('color: rgba(42, 3, 82, 1)')

			put_table(
				table,
				scope='tmp_res'
			).style('opacity: 0.8; font-size: 25px; table-layout: fixed; width: 100%;')

	def main_window(self):
		with use_scope(self.mp_scope, clear=True):
			with open('bg.png', 'rb') as img:
				image = img.read()
			put_scope(
				'word'
			).style(
				f'border: 1px solid; '
				f'width: 100%; '
				f'padding: 10px; '
				f'border-radius: 10px; '
				f'margin: 0 0; '
				f'background: url("http://pinsknews.by/wp-content/uploads/2021/05/%D0%A1%D0%BA%D0%B0%D0%BD%D0%B2%D0%BE%D1%80%D0%B4.jpg");'
			)

			put_text(
				'|S|C|A|N|W|O|R|D|E|R|', scope='word'
			).style(
				'color: rgba(42, 3, 82, 1); '
				'font-family: DejaVu Sans Mono, sans-serif; '
				'font-weight: bold; '
				'text-align: center; '
				'font-size: 180%'
			)

			put_input(
				'word',
				type=TEXT,
				scope='word',
				value=self.mask,
				help_text='маска слова ("-" любая буква) (пример: -ка--о-д)'
			).style('font-size: 150%; font-weight: bold;')

			put_input(
				'required_',
				type=TEXT,
				scope='word',
				value=self.required,
				help_text='обязательные к использованию буквы например: рдс'
			).style('font-size: 110%; font-weight: bold;')

			put_input(
				'prohibited_common',
				type=TEXT,
				scope='word',
				value=self.prohibited_common,
				help_text='запрещенные буквы во всём слове например: цхптс'
			).style('font-size: 110%; font-weight: bold;')

			put_input(
				'prohibited_positions',
				type=TEXT,
				scope='word',
				value=self.prohibited_positions,
				help_text='запрещенные буквы по позициям, например: 1:цптс;2:рми'
			).style('font-size: 110%; font-weight: bold;')

			put_row(
				[
					put_button(
						'ПОИСК',
						scope='word',
						onclick=lambda: self.click_ok()
					),
					put_scope(
						'word_info'
					).style('align: right; text-align: right')
				],
				scope='word',
				size='85% 15%'
			)


def Scanworder():
	# set environment
	session.set_env(title=f'ScanWorder', output_animation=True)  # output_max_width='60%',
	
	program = MainProgram()
	program.main_window()  # show main window and start


def run(port):
	start_server(debug=False, port=port, cdn=False, applications=Scanworder)
	