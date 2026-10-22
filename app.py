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
import importlib.util
import queue
import re
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urlsplit, unquote
import uuid
import shutil

STATE = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'VideoLivre'
APP_VERSION = '1.1.2'
QUALITIES = ['Melhor disponível', 'Até 1080p', 'Até 720p', 'Até 480p', 'Somente áudio (MP3)']
STATUS_LABELS = {
    'queued': 'Na fila', 'paused': 'Pausado', 'downloading': 'Baixando',
    'finalizing': 'Finalizando', 'completed': 'Concluído', 'error': 'Erro',
}
LEGACY_STATUS = {
    'Na fila': 'queued', 'Pausado': 'paused', 'Concluído': 'completed',
    'Erro': 'error', 'Finalizando': 'finalizing',
}


def normalize_job(raw):
    if not isinstance(raw, dict):
        return None
    url, folder, quality = raw.get('url'), raw.get('folder'), raw.get('quality')
    if not all(isinstance(v, str) and v.strip() for v in (url, folder, quality)) or quality not in QUALITIES:
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return None
    except ValueError:
        return None
    status = raw.get('status', 'paused')
    if status in LEGACY_STATUS:
        status = LEGACY_STATUS[status]
    if status == 'queued':
        status = 'paused'
    if status not in STATUS_LABELS or status in ('downloading', 'finalizing'):
        status = 'paused'
    job = {
        'id': raw.get('id') if isinstance(raw.get('id'), str) and raw.get('id') else uuid.uuid4().hex,
        'url': url.strip(), 'folder': folder, 'quality': quality, 'status': status,
        'progress': raw.get('progress') if isinstance(raw.get('progress'), (int, float)) else None,
    }
    for key in ('name', 'file', 'error_summary', 'error_details'):
        if isinstance(raw.get(key), str):
            job[key] = raw[key][:4000]
    if isinstance(raw.get('creator_handle'), str):
        job['creator_handle'] = raw['creator_handle'][:80]
    if isinstance(raw.get('manual_credit'), str):
        job['manual_credit'] = format_credit(raw['manual_credit'])
    return job


def clean_credit(text):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', text).strip().strip('. ')[:80].rstrip('. ')


def format_credit(text):
    name = clean_credit(text).lstrip('@').strip()
    return '@' + name if name else ''


def safe_error(text):
    text = re.sub(r'(?i)(https?://[^\s?]+)\?[^\s]+', r'\1?[parâmetros removidos]', text)
    text = re.sub(r'(?i)(cookie|authorization|token|password|senha)(\s*[:=]\s*)\S+', r'\1\2[removido]', text)
    return text[-4000:]


def command(job):
    worker = [sys.executable, '--worker'] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).resolve()), '--worker']
    args = ['--ignore-config', '--no-playlist', '--newline', '--progress', '--no-colors', '--windows-filenames',
            '--continue', '--no-overwrites', '--socket-timeout', '20', '--retries', '3',
            '--ffmpeg-location', str(BASE / 'ffmpeg.exe'), '-P', job['folder'],
            '-o', '%(title).150B [%(id)s].%(ext)s', '--encoding', 'utf-8',
            '--print', 'after_move:FILE:%(filepath)s',
            '--print', 'after_move:CHANNEL_URL:%(channel_url)s',
            '--print', 'after_move:UPLOADER_URL:%(uploader_url)s',
            '--print', 'after_move:UPLOADER_ID:%(uploader_id)s']
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
        load_warning = None
        def restore_queue(data):
            if not isinstance(data, dict):
                raise ValueError('Formato da fila inválido')
            stored_folder = data.get('folder')
            if isinstance(stored_folder, str) and stored_folder.strip():
                self.folder.set(stored_folder)
            raw_jobs = data.get('jobs', [])
            if not isinstance(raw_jobs, list):
                raise ValueError('Lista de downloads inválida')
            seen = set()
            warning = None
            for raw in raw_jobs:
                job = normalize_job(raw)
                if job and job['id'] not in seen:
                    seen.add(job['id'])
                    self.jobs.append(job)
                else:
                    warning = 'Alguns itens inválidos ou repetidos da fila foram ignorados.'
            return warning
        try:
            queue_file = STATE / 'queue.json'
            data = json.loads(queue_file.read_text(encoding='utf-8'))
            load_warning = restore_queue(data)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError) as exc:
            queue_file = STATE / 'queue.json'
            if queue_file.exists():
                try:
                    backup = queue_file.with_name('queue.corrompida.json')
                    shutil.copy2(queue_file, backup)
                    load_warning = f'A fila estava danificada; uma cópia foi salva em {backup}.'
                    previous = STATE / 'queue.backup.json'
                    backup_data = json.loads(previous.read_text(encoding='utf-8'))
                    restored_warning = restore_queue(backup_data)
                    load_warning += ' A última fila válida foi restaurada do backup.'
                    if restored_warning:
                        load_warning += ' ' + restored_warning
                except OSError:
                    load_warning = f'Não foi possível ler a fila salva: {exc}'
                except (ValueError, TypeError):
                    self.jobs = []
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
        credits = ttk.Frame(main)
        credits.pack(fill='x', pady=(10, 0))
        ttk.Label(credits, text='Créditos / @ do criador:').pack(side='left')
        self.credit = tk.StringVar()
        ttk.Entry(credits, textvariable=self.credit).pack(side='left', fill='x', expand=True, padx=(8, 0))
        ttk.Label(main, text='Opcional: digite @usuario ou o nome. Em branco, tenta identificar automaticamente.', wraplength=700).pack(anchor='w', pady=(4, 0))
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
        for label, fn in [('Pausar', self.pause), ('Retomar / tentar novamente', self.resume), ('Remover', self.remove), ('Ver erro', self.show_error), ('Copiar diagnóstico', self.copy_diagnostic)]:
            ttk.Button(buttons, text=label, command=fn).pack(side='left', padx=(0, 6))
        history_buttons = ttk.Frame(main)
        history_buttons.pack(fill='x', pady=(0, 10), before=table)
        ttk.Button(history_buttons, text='Limpar lista de baixados', command=self.clear_downloaded).pack(side='left', padx=(0, 6))
        ttk.Button(history_buttons, text='Ir até a pasta do download', command=self.open_folder).pack(side='left')
        initial_notice = load_warning or ('Pronto. Adicione um link para começar.' if not self.jobs else 'Fila restaurada. Downloads interrompidos estão pausados.')
        self.notice = tk.StringVar(value=initial_notice)
        ttk.Label(footer, textvariable=self.notice, wraplength=700).pack(anchor='w', pady=(8, 8))
        self.log = tk.Text(footer, height=3, font=('Consolas', 9), bg='white', fg='#243949', relief='solid', bd=1, state='disabled', wrap='word')
        self.log.pack(fill='x')
        ttk.Label(footer, text='A compatibilidade e a retomada dependem do site. Vídeos protegidos por DRM não são suportados.', wraplength=700, font=('Segoe UI', 9)).pack(anchor='w', pady=(8, 0))
        self.title(f'VideoLivre {APP_VERSION} — downloads de vídeo')
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()
        self.after(150, self.tick)
        self.url.focus_set()

    def save(self):
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            queue_file = STATE / 'queue.json'
            temp = STATE / 'queue.tmp'
            if queue_file.exists():
                try:
                    shutil.copy2(queue_file, STATE / 'queue.backup.json')
                except OSError:
                    pass
            temp.write_text(json.dumps({'version': 2, 'folder': self.folder.get(), 'jobs': self.jobs}, ensure_ascii=False), encoding='utf-8')
            temp.replace(queue_file)
            return True
        except OSError as exc:
            self.notice.set(f'Não foi possível salvar a fila: {exc}')
            return False

    def refresh(self):
        ids = {j['id'] for j in self.jobs}
        for iid in self.tree.get_children():
            if iid not in ids:
                self.tree.delete(iid)
        for job in self.jobs:
            progress = job.get('progress')
            status = STATUS_LABELS.get(job.get('status'), 'Pausado')
            if job.get('status') == 'downloading' and progress is not None:
                status += f' {progress:.1f}%'
            values = (job.get('name') or job['url'], job['quality'], status)
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
            probe = Path(self.folder.get()) / '.videolivre_write_check'
            probe.write_text('', encoding='utf-8')
            probe.unlink()
            if not (BASE / 'ffmpeg.exe').is_file() and not shutil.which('ffmpeg'):
                if not messagebox.askyesno('FFmpeg não encontrado', 'O FFmpeg é necessário para combinar vídeo e áudio ou converter MP3. Deseja adicionar mesmo assim?'):
                    return
        except OSError as e:
            messagebox.showerror('Pasta indisponível', str(e))
            return
        if not getattr(sys, 'frozen', False) and importlib.util.find_spec('yt_dlp') is None:
            messagebox.showerror('yt-dlp não encontrado', 'Instale as dependências com: python -m pip install -r requirements.txt')
            return
        credit = format_credit(self.credit.get())
        if self.credit.get().strip() and not credit:
            messagebox.showinfo('Confira os créditos', 'Digite um nome ou @ válido para o arquivo.')
            return
        self.jobs.append(dict(id=uuid.uuid4().hex, url=url, folder=self.folder.get(), quality=self.quality.get(), status='queued', progress=None, manual_credit=credit))
        self.url.delete(0, 'end')
        self.credit.set('')
        self.save()
        self.refresh()

    def pause(self):
        job = self.selected()
        if not job:
            self.notice.set('Selecione um download na lista.')
            return
        if job['id'] == self.active:
            self.stopped.add(job['id'])
            job['status'] = 'paused'
            self.kill_child()
        elif job['status'] == 'queued':
            job['status'] = 'paused'
            self.save()
            self.refresh()

    def kill_child(self):
        if self.proc and self.proc.poll() is None:
            proc = self.proc
            def stop_process():
                try:
                    proc.terminate()
                    proc.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
                except (OSError, subprocess.SubprocessError):
                    pass
            threading.Thread(target=stop_process, daemon=True).start()

    def resume(self):
        job = self.selected()
        if job and job['status'] in ('paused', 'error') and job['id'] != self.active:
            job['status'] = 'queued'
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
        completed = [j for j in self.jobs if j['status'] == 'completed' and j['id'] != self.active]
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

    @staticmethod
    def creator_handle(url, uploader_id):
        try:
            parsed = urlsplit(url)
            path = unquote(parsed.path)
        except ValueError:
            path = ''
            parsed = None
        match = re.search(r'(?:^|/)@([A-Za-z0-9._-]{2,60})(?:/|$)', path)
        if match:
            return '@' + match.group(1)
        if parsed and parsed.hostname:
            host = parsed.hostname.lower().removeprefix('www.')
            supported_profiles = ('instagram.com', 'tiktok.com', 'x.com', 'twitter.com', 'twitch.tv', 'facebook.com')
            if any(host == domain or host.endswith('.' + domain) for domain in supported_profiles):
                parts = [part for part in path.split('/') if part]
                if parts and parts[0].lower() not in ('p', 'reel', 'reels', 'video', 'videos', 'watch', 'user', 'channel', 'c', 'profile.php'):
                    if re.fullmatch(r'[A-Za-z0-9._-]{2,60}', parts[0]):
                        return '@' + parts[0].lstrip('@')
        if isinstance(uploader_id, str) and re.fullmatch(r'@[A-Za-z0-9._-]{2,60}', uploader_id):
            return uploader_id
        return None

    def add_creator_to_filename(self, job):
        handle = format_credit(job.get('manual_credit') or job.get('creator_handle') or '')
        file = Path(job.get('file', '')) if job.get('file') else None
        if not file or not file.is_file():
            return
        base = re.sub(r'\s\[[^\[\]]+\]$', '', file.stem)
        if base == file.stem:
            return
        stem = base + (f' [{handle}]' if handle else '')
        target = file.with_name(stem + file.suffix)
        index = 2
        while target.exists():
            target = file.with_name(f'{stem} ({index}){file.suffix}')
            index += 1
        try:
            file.rename(target)
            job['file'] = str(target)
            job['name'] = target.name
        except OSError as exc:
            job['error_details'] = f"Download concluído, mas não foi possível incluir o crédito no nome do arquivo: {exc}"

    def show_error(self):
        job = self.selected()
        if not job:
            self.notice.set('Selecione um download para ver os detalhes.')
            return
        details = job.get('error_details') or job.get('error_summary') or 'Este item não tem erro registrado.'
        messagebox.showinfo('Detalhes do download', details)

    def copy_diagnostic(self):
        job = self.selected()
        if not job:
            self.notice.set('Selecione um download para copiar o diagnóstico.')
            return
        text = '\n'.join([
            f'VideoLivre {APP_VERSION}', f'Situação: {STATUS_LABELS.get(job.get("status"), "Pausado")}',
            f'Qualidade: {job.get("quality", "")}', f'Endereço: {safe_error(job.get("url", ""))}',
            f'Erro: {safe_error(job.get("error_details") or job.get("error_summary") or "sem erro registrado")}',
        ])
        self.clipboard_clear()
        self.clipboard_append(text)
        self.notice.set('Diagnóstico copiado. Confira o texto antes de compartilhá-lo.')

    @staticmethod
    def classify_error(text):
        value = text.lower()
        if any(x in value for x in ('timed out', 'timeout', 'connection reset', 'unable to download webpage', 'network is unreachable')):
            return 'Falha de conexão. Confira sua internet e tente novamente.'
        if any(x in value for x in ('requested format is not available', 'format is not available')):
            return 'Formato indisponível. Tente outra qualidade.'
        if any(x in value for x in ('private video', 'video unavailable', 'not available', 'has been removed', '404 not found')):
            return 'Vídeo indisponível ou removido. Confira o link e as restrições do site.'
        if any(x in value for x in ('sign in', 'login required', 'authentication', 'cookies')):
            return 'O site exige autenticação. Confira se o vídeo pode ser acessado no navegador.'
        if 'ffmpeg' in value:
            return 'Falha ao combinar ou converter o arquivo. Confira a instalação do FFmpeg.'
        if any(x in value for x in ('permission denied', 'no space left', 'disk full', 'cannot write')):
            return 'Não foi possível gravar na pasta. Confira as permissões e o espaço livre.'
        return 'Erro não identificado. Confira os detalhes do download.'

    def worker(self, job):
        code = 1
        try:
            env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
            self.proc = subprocess.Popen(command(job), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, encoding='utf-8', errors='replace', env=env,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
            if job['id'] in self.stopped or self.closing:
                self.kill_child()
            for line in self.proc.stdout:
                self.events.put(('line', job['id'], line.strip()))
            code = self.proc.wait()
        except Exception as e:
            self.events.put(('failure', job['id'], safe_error(str(e))))
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
                        job['status'] = 'downloading'
                        job['progress'] = float(percent.group(1))
                    if value.startswith('FILE:'):
                        job['file'] = value[5:]
                        job['name'] = Path(value[5:]).name
                    elif value.startswith('CHANNEL_URL:'):
                        job['creator_handle'] = self.creator_handle(value[len('CHANNEL_URL:'):], None) or job.get('creator_handle')
                    elif value.startswith('UPLOADER_URL:'):
                        job['creator_handle'] = self.creator_handle(value[len('UPLOADER_URL:'):], None) or job.get('creator_handle')
                    elif value.startswith('UPLOADER_ID:'):
                        job['creator_handle'] = self.creator_handle('', value[len('UPLOADER_ID:'):]) or job.get('creator_handle')
                    if value.startswith('[Merger]') or value.startswith('[ExtractAudio]'):
                        job['status'] = 'finalizing'
                        job['progress'] = None
                    if 'ERROR:' in value or 'error:' in value.lower():
                        job['error_details'] = safe_error(value)
                        job['error_summary'] = self.classify_error(value)
                elif kind == 'failure':
                    job['error_details'] = value
                    job['error_summary'] = self.classify_error(value)
                else:
                    job['status'] = 'paused' if iid in self.stopped else ('completed' if value == 0 else 'error')
                    if value == 0:
                        self.add_creator_to_filename(job)
                    if value and not job.get('error_summary'):
                        job['error_summary'] = 'Erro não identificado. Confira os detalhes.'
                        job.setdefault('error_details', f'yt-dlp encerrou com código {value}.')
                    job['progress'] = 100.0 if value == 0 else None
                    self.active = None
                    self.proc = None
                    self.notice.set('Download concluído. Use Ir até a pasta para encontrar o arquivo.' if job['status'] == 'completed' else 'Pausado; use Retomar.' if job['status'] == 'paused' else 'Não foi possível baixar. Selecione o item e use Ver erro.')
                    self.save()
                self.refresh()
        except queue.Empty:
            pass
        if self.active is None and not self.closing:
            job = next((j for j in self.jobs if j['status'] == 'queued'), None)
            if job:
                self.active = job['id']
                job['status'] = 'downloading'
                self.save()
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
            if job['id'] == self.active or job['status'] == 'queued':
                job['status'] = 'paused'
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

