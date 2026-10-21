"""VideoLivre: interface local para yt-dlp. Python 3.11+ / Windows."""
import sys
import os
from pathlib import Path

BASE = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent

if '--worker' in sys.argv:
    import yt_dlp
    yt_dlp.main(sys.argv[sys.argv.index('--worker') + 1:])
    raise SystemExit

import json
import queue
import re
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urlsplit
import uuid
import shutil

STATE = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'VideoLivre'
QUALITIES = ['Melhor disponível', 'Até 1080p', 'Até 720p', 'Até 480p', 'Somente áudio (MP3)']


def command(job):
    worker = [sys.executable, '--worker'] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).resolve()), '--worker']
    args = ['--ignore-config', '--no-playlist', '--newline', '--progress', '--no-colors', '--windows-filenames',
            '--continue', '--no-overwrites', '--socket-timeout', '20', '--retries', '3',
            '--ffmpeg-location', str(BASE / 'ffmpeg.exe'), '-P', job['folder'],
            '-o', '%(title).150B [%(id)s].%(ext)s', '--print', 'after_move:FILE:%(filepath)s']
    quality = job['quality']
    node = shutil.which('node')
    if node:
        args += ['--js-runtimes', 'node:' + node]
    if quality == QUALITIES[-1]:
        args += ['-f', 'bestaudio/best', '-x', '--audio-format', 'mp3']
    else:
        cap = {'Até 1080p': 1080, 'Até 720p': 720, 'Até 480p': 480}.get(quality)
        selector = f'bv*[height<={cap}]+ba/b[height<={cap}]' if cap else 'bv*+ba/b'
        args += ['-f', selector, '--merge-output-format', 'mkv']
    return worker + args + ['--', job['url']]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('VideoLivre — downloads de vídeo')
        self.geometry('980x710')
        self.minsize(780, 660)
        self.configure(bg='#f3f5f7')
        self.events = queue.Queue()
        self.proc = None
        self.active = None
        self.stopped = set()
        self.jobs = []
        self.closing = False
        self.folder = tk.StringVar(value=str(Path.home() / 'Downloads' / 'VideoLivre'))
        try:
            data = json.loads((STATE / 'queue.json').read_text(encoding='utf-8'))
            self.folder.set(data['folder'])
            self.jobs = data['jobs']
            for job in self.jobs:
                if job['status'].startswith('Baixando') or job['status'] in ('Na fila', 'Finalizando'):
                    job['status'] = 'Pausado'
        except (OSError, ValueError, KeyError, TypeError):
            self.jobs = []
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10), background='#f3f5f7', foreground='#182b3a')
        style.configure('TButton', padding=(14, 8))
        style.configure('Primary.TButton', background='#076b61', foreground='white')
        style.map('Primary.TButton', background=[('active', '#08594f')])
        style.configure('Treeview', rowheight=34, background='white', fieldbackground='white')
        style.configure('Treeview.Heading', padding=8, font=('Segoe UI', 10, 'bold'))
        main = ttk.Frame(self, padding=24)
        main.pack(fill='both', expand=True)
        ttk.Label(main, text='VideoLivre', font=('Segoe UI', 25, 'bold')).pack(anchor='w')
        ttk.Label(main, text='Cole um link. Escolha a qualidade. Salve no seu computador.').pack(anchor='w', pady=(3, 20))
        ttk.Label(main, text='Link do vídeo').pack(anchor='w')
        line = ttk.Frame(main)
        line.pack(fill='x', pady=(6, 12))
        self.url = ttk.Entry(line, font=('Segoe UI', 11))
        self.url.pack(side='left', fill='x', expand=True, ipady=6)
        self.url.bind('<Return>', lambda _: self.add())
        ttk.Button(line, text='Colar link', command=self.paste).pack(side='left', padx=(8, 0))
        options = ttk.Frame(main)
        options.pack(fill='x')
        self.quality = ttk.Combobox(options, values=QUALITIES, state='readonly', width=25)
        self.quality.set(QUALITIES[0])
        self.quality.pack(side='left', ipady=5)
        ttk.Button(options, text='Adicionar à fila', style='Primary.TButton', command=self.add).pack(side='right')
        destination = ttk.Frame(main)
        destination.pack(fill='x', pady=(12, 20))
        ttk.Label(destination, text='Salvar em:').pack(side='left')
        ttk.Entry(destination, textvariable=self.folder, state='readonly').pack(side='left', fill='x', expand=True, padx=8)
        ttk.Button(destination, text='Escolher pasta', command=self.choose).pack(side='left')
        ttk.Label(main, text='Seus downloads', font=('Segoe UI', 13, 'bold')).pack(anchor='w', pady=(0, 8))
        footer = ttk.Frame(main)
        footer.pack(side='bottom', fill='x')
        table = ttk.Frame(main)
        table.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(table, height=4, columns=('name', 'quality', 'status'), show='headings', selectmode='browse')
        for key, label, width in [('name', 'Vídeo / link', 430), ('quality', 'Qualidade', 150), ('status', 'Situação', 180)]:
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=100)
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        buttons = ttk.Frame(main)
        buttons.pack(fill='x', pady=(0, 8), before=table)
        for label, fn in [('Pausar', self.pause), ('Retomar / tentar novamente', self.resume), ('Remover', self.remove)]:
            ttk.Button(buttons, text=label, command=fn).pack(side='left', padx=(0, 6))
        history_buttons = ttk.Frame(main)
        history_buttons.pack(fill='x', pady=(0, 10), before=table)
        ttk.Button(history_buttons, text='Limpar lista de baixados', command=self.clear_downloaded).pack(side='left', padx=(0, 6))
        ttk.Button(history_buttons, text='Ir até a pasta do download', command=self.open_folder).pack(side='left')
        self.notice = tk.StringVar(value='Pronto. Adicione um link para começar.' if not self.jobs else 'Fila restaurada. Selecione um item e clique em Retomar.')
        ttk.Label(footer, textvariable=self.notice, wraplength=700).pack(anchor='w', pady=(8, 8))
        self.log = tk.Text(footer, height=3, font=('Consolas', 9), bg='white', fg='#243949', relief='solid', bd=1, state='disabled', wrap='word')
        self.log.pack(fill='x')
        ttk.Label(footer, text='A compatibilidade e a retomada dependem do site. Vídeos protegidos por DRM não são suportados.', wraplength=700, font=('Segoe UI', 9)).pack(anchor='w', pady=(8, 0))
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()
        self.after(150, self.tick)
        self.url.focus_set()

    def save(self):
        STATE.mkdir(parents=True, exist_ok=True)
        temp = STATE / 'queue.tmp'
        temp.write_text(json.dumps({'folder': self.folder.get(), 'jobs': self.jobs}, ensure_ascii=False), encoding='utf-8')
        temp.replace(STATE / 'queue.json')

    def refresh(self):
        ids = {j['id'] for j in self.jobs}
        for iid in self.tree.get_children():
            if iid not in ids:
                self.tree.delete(iid)
        for job in self.jobs:
            values = (job.get('name') or job['url'], job['quality'], job['status'])
            if self.tree.exists(job['id']):
                self.tree.item(job['id'], values=values)
            else:
                self.tree.insert('', 'end', iid=job['id'], values=values)

    def selected(self):
        selected = self.tree.selection()
        return next((j for j in self.jobs if selected and j['id'] == selected[0]), None)

    def paste(self):
        try:
            self.url.delete(0, 'end')
            self.url.insert(0, self.clipboard_get().strip())
        except tk.TclError:
            self.notice.set('Copie o link do vídeo antes de colar.')

    def choose(self):
        folder = filedialog.askdirectory(initialdir=self.folder.get())
        if folder:
            self.folder.set(folder)
            self.save()

    def add(self):
        url = self.url.get().strip()
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in ('http', 'https') and bool(parsed.hostname)
        except ValueError:
            valid = False
        if not valid:
            messagebox.showinfo('Confira o link', 'Cole um endereço completo começando com https:// ou http://.')
            return
        try:
            Path(self.folder.get()).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror('Pasta indisponível', str(e))
            return
        self.jobs.append(dict(id=uuid.uuid4().hex, url=url, folder=self.folder.get(), quality=self.quality.get(), status='Na fila'))
        self.url.delete(0, 'end')
        self.save()
        self.refresh()

    def pause(self):
        job = self.selected()
        if not job:
            self.notice.set('Selecione um download na lista.')
            return
        if job['id'] == self.active:
            self.stopped.add(job['id'])
            self.kill_child()
        elif job['status'] == 'Na fila':
            job['status'] = 'Pausado'
            self.save()
            self.refresh()

    def kill_child(self):
        if self.proc and self.proc.poll() is None:
            subprocess.run(['taskkill', '/PID', str(self.proc.pid), '/T', '/F'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)

    def resume(self):
        job = self.selected()
        if job and job['status'] in ('Pausado', 'Erro') and job['id'] != self.active:
            job['status'] = 'Na fila'
            self.stopped.discard(job['id'])
            self.save()
            self.refresh()

    def remove(self):
        job = self.selected()
        if job and job['id'] == self.active:
            self.notice.set('Pause o download antes de removê-lo.')
        elif job:
            self.jobs.remove(job)
            self.save()
            self.refresh()
            self.notice.set('Item removido da fila. Os arquivos foram mantidos na pasta.')

    def clear_downloaded(self):
        completed = [j for j in self.jobs if j['status'] == 'Concluído' and j['id'] != self.active]
        if not completed:
            self.notice.set('Não há downloads concluídos para limpar.')
            return
        self.jobs = [j for j in self.jobs if j not in completed]
        self.save()
        self.refresh()
        self.notice.set(f'{len(completed)} download(s) concluído(s) removido(s) da lista. Seus arquivos continuam na pasta.')

    def open_folder(self):
        job = self.selected()
        file = Path(job['file']) if job and job.get('file') else None
        path = file.parent if file else Path(job['folder'] if job else self.folder.get())
        try:
            if not path.is_dir():
                self.notice.set('A pasta não existe mais. Confira o destino do download.')
                return
            os.startfile(str(path))
            self.notice.set(f'Pasta aberta: {path}')
        except OSError as e:
            messagebox.showerror('Não foi possível abrir a pasta', str(e))

    def worker(self, job):
        code = 1
        try:
            env = dict(os.environ, PYTHONIOENCODING='utf-8')
            self.proc = subprocess.Popen(command(job), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, encoding='utf-8', errors='replace', env=env,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
            if job['id'] in self.stopped or self.closing:
                self.kill_child()
            for line in self.proc.stdout:
                self.events.put(('line', job['id'], line.strip()))
            code = self.proc.wait()
        except Exception as e:
            self.events.put(('line', job['id'], str(e)))
        self.events.put(('done', job['id'], code))

    def tick(self):
        try:
            while True:
                kind, iid, value = self.events.get_nowait()
                job = next((j for j in self.jobs if j['id'] == iid), None)
                if not job:
                    continue
                if kind == 'line':
                    self.log.configure(state='normal')
                    self.log.insert('end', value + '\n')
                    if int(self.log.index('end-1c').split('.')[0]) > 250:
                        self.log.delete('1.0', '50.0')
                    self.log.see('end')
                    self.log.configure(state='disabled')
                    percent = re.search(r'\[download\]\s+([\d.]+)%', value)
                    if percent:
                        job['status'] = 'Baixando ' + percent.group(1) + '%'
                    if value.startswith('FILE:'):
                        job['file'] = value[5:]
                        job['name'] = Path(value[5:]).name
                    if value.startswith('[Merger]') or value.startswith('[ExtractAudio]'):
                        job['status'] = 'Finalizando'
                else:
                    job['status'] = 'Pausado' if iid in self.stopped else ('Concluído' if value == 0 else 'Erro')
                    self.active = None
                    self.proc = None
                    self.notice.set('Download concluído. Use Abrir pasta para encontrar o arquivo.' if job['status'] == 'Concluído' else 'Pausado; use Retomar.' if job['status'] == 'Pausado' else 'Não foi possível baixar. Veja o motivo no painel abaixo; confira o link e tente novamente.')
                    self.save()
                self.refresh()
        except queue.Empty:
            pass
        if self.active is None and not self.closing:
            job = next((j for j in self.jobs if j['status'] == 'Na fila'), None)
            if job:
                self.active = job['id']
                job['status'] = 'Baixando'
                self.notice.set('Consultando o site e preparando o download…')
                self.refresh()
                threading.Thread(target=self.worker, args=(dict(job),), daemon=True).start()
        self.after(150, self.tick)

    def close(self):
        self.closing = True
        if self.active:
            self.stopped.add(self.active)
            self.kill_child()
        for job in self.jobs:
            if job['id'] == self.active or job['status'] == 'Na fila':
                job['status'] = 'Pausado'
        self.save()
        self.destroy()


if __name__ == '__main__':
    if os.name == 'nt':
        import ctypes
        ctypes.windll.kernel32.CreateMutexW.restype = ctypes.c_void_p
        instance_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'Local\\VideoLivreDesktop')
        if ctypes.windll.kernel32.GetLastError() == 183:
            ctypes.windll.user32.MessageBoxW(None, 'O VideoLivre já está aberto. Procure a janela na barra de tarefas.', 'VideoLivre', 64)
            raise SystemExit
    if getattr(sys, 'frozen', False) and os.name == 'nt':
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    App().mainloop()
