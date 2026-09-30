"""The window in English: every Russian string it shows, and its English.

Keyed by the Russian exactly as the code has it, templates and all -- the
numbered pieces {0}, {1} are the same in both, in whatever order a sentence
wants them. A string missing here shows in Russian; qa/headless/test_lang.py
says which ones are missing before that can happen.

The names the screens and the formats have in the files -- Top, Bottom,
Lamels, Frame, Sound, Kinetic, Premultiplied, Hap Q Alpha -- are the same in
both languages, and so are the words the lists said in 0.3 (Fit, Clean,
Keep, Flat, ReBake...), so a settings file from then reads the same.
"""

EN: dict = {
    # -- the modes, the layers, the checks, the cards ------------------------
    'Превью': 'Preview',
    'Развертка': 'Flat',
    'Инспектор': 'Inspection',
    'Перепечка': 'ReBake',
    'Корпус': 'Body',
    'Оболочка': 'Shell',
    'Заглушка': 'Blank',
    'Видеокарта': 'Graphics card',
    'Сжатые текстуры': 'Compressed textures',
    'ffmpeg с Hap': 'ffmpeg with Hap',
    'верхний экран': 'top screen',
    'нижний экран': 'bottom screen',
    'ламели': 'lamellas',
    'накладка': 'overlay',
    'звук': 'sound',
    'моторы': 'motors',

    # -- the transport ---------------------------------------------------------
    'В начало': 'To the start',
    'В начало.  Ctrl со стрелкой влево делает то же.':
        'To the start.  Ctrl with the left arrow does the same.',
    'На кадр назад': 'A frame back',
    'На кадр назад по сетке просмотра.  Стрелка влево делает то же.':
        'A frame back on the grid it is watched at.  The left arrow does the same.',
    'Играть': 'Play',
    'Играть или остановить.  Пробел делает то же — отовсюду, кроме поля, в котором печатают.':
        'Play or stop.  The space bar does the same, from anywhere but a field being typed into.',
    'На кадр вперёд': 'A frame on',
    'На кадр вперёд по сетке просмотра.  Стрелка вправо делает то же.':
        'A frame on, on the grid it is watched at.  The right arrow does the same.',
    'В конец': 'To the end',
    'В конец.  Ctrl со стрелкой вправо делает то же.':
        'To the end.  Ctrl with the right arrow does the same.',
    'Камера сужается до центрального окна такой формы: всё, что она видит сверху донизу, остаётся, отдаются только пустые бока. Из разрешения не теряется ничего.':
        'The camera narrows to a centred window of this shape: everything it sees from top to bottom stays, only the empty sides go. No resolution is lost.',
    'Родное': 'Native',
    'Половина': 'Half',
    'Четверть': 'Quarter',

    # -- drafts ------------------------------------------------------------------
    'У этого шоу есть черновик: правок {0}, последняя записана {1}.':
        'This show has a draft: {0} edits, the last written {1}.',
    '\n\n«Открыть файл заново» не стирает черновик — он уходит в drafts\\old.':
        '\n\n"Open the file afresh" does not delete the draft: it goes to drafts\\old.',
    '{0} · колесо — ближе, двойной щелчок — сброс':
        '{0} · wheel to zoom, double-click to reset',

    # -- the machine check -------------------------------------------------------
    'Что есть на этой машине': 'What this machine has',
    'Проверяется один раз, при первом запуске. Ничего не устанавливается и не прописывается в PATH: скачанное ложится в папку рядом с программой, и удалить её — значит отменить всё.':
        'Checked once, on the first run. Nothing is installed and nothing goes into PATH: what is downloaded goes into a folder beside the program, and deleting that folder undoes all of it.',
    'Продолжить': 'Continue',
    'качаю с {0}…': 'downloading from {0}…',
    'Не скачалось: {0}': 'The download failed: {0}',
    'Цепочка:': 'Chain:',
    'Секции по Bottom:': 'Sections on Bottom:',
    'Скачать {0} ({1} МБ)': 'Download {0} ({1} MB)',
    'На этой машине вьювер работать не сможет: нет {0}.':
        'The viewer cannot run on this machine: {0} is missing.',
    '{0:.0f} из {1:.0f} МБ': '{0:.0f} of {1:.0f} MB',
    '{0:.0f} МБ': '{0:.0f} MB',
    '   {0:7.1f} с   {1}': '   {0:7.1f} s   {1}',
    'есть': 'present',
    'НЕТ — нужно': 'MISSING, needed',
    'нет': 'missing',
    'без {0} {1}': 'without {0}, {1}',
    'Всё на месте.': 'Everything is in place.',
    'Смотреть можно — всё нужное для этого есть. ':
        'Watching works: everything it needs is here. ',
    'Нет: {0}.': 'Missing: {0}.',

    # -- the source cards ----------------------------------------------------------
    'Заменить': 'Replace',
    'Выбрать': 'Choose',
    'Выбрать файл для этой строки. Перетащить его на карточку — то же самое.':
        'Choose a file for this card. Dragging one onto the card does the same.',
    'Убрать файл из строки. Сам файл не трогается.':
        'Take the file off the card. The file itself is not touched.',
    'Вписать': 'Fit',
    'Растянуть': 'Stretch',
    '«Вписать» сохраняет пропорции кадра и ставит его по центру, а экран остаётся виден по бокам. «Растянуть» тянет кадр к углам экрана, какой бы формы кадр ни был.':
        'Fit keeps the frame\'s proportions and centres it, and the screen shows on either side. Stretch pulls the frame to the screen\'s corners, whatever shape it is.',
    'Перетащите WAV или выберите файл': 'Drop a WAV here or choose a file',
    'Перетащите JSON моторов или выберите файл':
        'Drop a motor JSON here or choose a file',
    'Перетащите ролик или картинку, или выберите файл':
        'Drop a movie or a picture here, or choose a file',
    'Громкость': 'Volume',
    'Яркость': 'Brightness',
    'Громкость: от тишины до файла как он есть':
        'Volume: from silence to the file as it is',
    'Яркость этого экрана, на глаз. 1.00 оставляет её такой, какой её делают геометрия и «Сравнять яркость». Двойной щелчок по карточке возвращает обратно.':
        'This screen\'s brightness, by eye. 1.00 leaves it as the geometry and Match brightness make it. A double-click on the card puts it back.',
    'Источники': 'Sources',
    'Источники — свернуть': 'Sources: fold away',
    'Источники — развернуть': 'Sources: unfold',
    '\n\nКарточки с файлами: что на каком экране, звук, моторы. Свёрнутые — картинке достаётся вся ширина окна.':
        '\n\nThe cards of files: what is on which screen, the sound, the motors. Folded, the picture gets the whole width of the window.',
    '{0} из {1} загружено': '{0} of {1} loaded',
    'ничего не загружено': 'nothing loaded',
    '{0}: пусто': '{0}: empty',
    '{0}x{1}  {2}  {3:g} к/с  {4:.2f} с': '{0}x{1}  {2}  {3:g} fps  {4:.2f} s',
    '{0}x{1} вписана в {2}x{3}  {4}': '{0}x{1} fitted into {2}x{3}  {4}',
    '{0} не открывается': '{0} does not open',
    'части {0} из {1}  ': 'parts {0} of {1}  ',

    # -- the link --------------------------------------------------------------------
    'Связать': 'Link',
    'Разъединить': 'Unlink',
    'Top и Bottom связаны': 'Top and Bottom are linked',
    'Top и Bottom не связаны': 'Top and Bottom are not linked',
    'Связывает ползунки Top и Bottom в том отношении, в каком они стоят на момент включения. Выставьте каждый так, чтобы экраны читались одинаково, нажмите это — и дальше любой из ползунков поднимает и опускает оба, не теряя баланса. Если одному упереться в край, останавливаются оба.':
        'Ties the Top and Bottom sliders together at the ratio they stand at when this is pressed. Set each so the screens read the same, press this, and from then on either slider moves both without losing the balance. If one reaches its end, both stop.',

    # -- the show's line -----------------------------------------------------------------
    'Открыть шоу…': 'Open show…',
    'Открыть .trix из редактора шоу. Файл только читается; ничего в него не пишется. Если у шоу есть черновик — спросит, продолжать ли его.':
        'Open a .trix from the show editor. The file is only read; nothing is written into it. If the show has a draft, you are asked whether to carry on with it.',
    'Новое шоу': 'New show',
    'Пустое шоу на 22 минуты, сразу в редакторе: файлы бросаются из проводника прямо на дорожки.':
        'An empty 22-minute show, straight into the editor: files are dropped from Explorer right onto the lanes.',
    'имя шоу': 'show name',
    'Имя шоу — project.name в .trix. Правится в редакторе.':
        'The show\'s name, project.name in the .trix. Edited in the editor.',
    '✎ Редактор': '✎ Editor',
    'Отпереть шоу: клипы тащатся, поля справа пишут в клип, лупы рисуются, файлы бросаются на дорожки. Каждая правка сама пишется в черновик рядом с программой (drafts); сам .trix не трогается никогда.':
        'Unlock the show: clips are dragged, the fields on the right write into the clip, loops are drawn, files are dropped onto lanes. Every edit is written by itself to a draft beside the program (drafts); the .trix itself is never touched.',
    'Отменить (Ctrl+Z)': 'Undo (Ctrl+Z)',
    'Вернуть (Ctrl+Y)': 'Redo (Ctrl+Y)',
    '+ кью': '+ cue',
    'Кью на кадре плейхеда, с тем же адресом, что у кью перед ним. Universe, channel и value — справа.':
        'A cue on the playhead\'s frame, with the address of the cue before it. Universe, channel and value are on the right.',
    'Удалить': 'Delete',
    'Удалить выбранный клип (Delete)': 'Delete the chosen clip (Delete)',
    'Вернуть файл': 'Revert to file',
    'Бросить черновик и открыть .trix как он есть. Черновик не стирается: уходит в drafts\\old.':
        'Drop the draft and open the .trix as it is. The draft is not deleted: it goes to drafts\\old.',
    'Отменить: {0} (Ctrl+Z)': 'Undo: {0} (Ctrl+Z)',
    'Нечего отменять': 'Nothing to undo',
    'Вернуть: {0} (Ctrl+Y)': 'Redo: {0} (Ctrl+Y)',
    'Нечего возвращать': 'Nothing to redo',
    'отменено': 'undone',
    'возвращено': 'redone',
    'нечего отменять': 'nothing to undo',
    'нечего возвращать': 'nothing to redo',
    '\n\nФайл шоу изменился после того, как черновик был начат: черновик сделан на прежней версии файла.':
        '\n\nThe show file has changed since the draft was begun: the draft was made on the earlier version of the file.',
    'Черновик': 'Draft',
    'Продолжить черновик': 'Carry on with the draft',
    'Открыть файл заново': 'Open the file afresh',
    'Отмена': 'Cancel',
    'черновик убран в drafts\\old\\{0}': 'the draft was put away in drafts\\old\\{0}',
    'черновик не записался: {0}': 'the draft was not written: {0}',
    'файлы на дорожку': 'files onto a lane',
    'Открыть шоу': 'Open show',
    'Шоу (*.trix);;Все файлы (*)': 'Shows (*.trix);;All files (*)',
    '{0}  —  показаны строки Просмотра': '{0}  —  showing the quick look\'s cards',
    'строки Просмотра как шоу · ': 'the quick look\'s cards as a show · ',
    'строки Просмотра': 'the quick look\'s cards',
    'черновик · правок {0}': 'draft · {0} edits',
    'черновик: {0}\nсам .trix не трогается': 'draft: {0}\nthe .trix itself is not touched',
    'черновик: {0}\n': 'draft: {0}\n',

    # -- over the picture --------------------------------------------------------------
    'Клавиши и мышь (?)': 'Keys and mouse (?)',
    'Ничего не загружено': 'Nothing loaded',
    'Перетащите ролики на карточки слева или выберите их здесь — по именам они разойдутся по экранам сами. Шоу из редактора площадки открывается как шоу.':
        'Drop movies onto the cards on the left or choose them here: by their names they go to their screens by themselves. A show from the venue\'s show editor opens as a show.',
    'Выбрать файлы…': 'Choose files…',
    'Выбрать файлы для экранов': 'Choose files for the screens',
    'Ролики, картинки, звук и моторы (*.mov *.mp4 *.m4v *.mkv *.avi *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga *.wav *.json);;Все файлы (*)':
        'Movies, pictures, sound and motors (*.mov *.mp4 *.m4v *.mkv *.avi *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga *.wav *.json);;All files (*)',
    'Сравнять яркость': 'Match brightness',
    'Экраны устроены по-разному: верхний — раздельные соты, четверть его площади тёмная, нижний почти сплошной, поэтому одинаковый белый на верхнем читается тусклее. Это приводит более яркий к более тусклому, чтобы они совпадали на всех уровнях, включая максимум. Выключено — показывает так, как есть в геометрии.':
        'The screens are built differently: the top one is separate cells with a quarter of its area dark, the bottom one is nearly solid, so the same white reads dimmer on the top. This brings the brighter down to the dimmer so the two match at every level, the maximum included. Off, they show as the geometry has them.',
    'Без изнанки верха': 'Solid top',
    'Убирает дальнюю сторону верхнего экрана, чтобы его собственная изнанка не просвечивала сквозь передние соты. Работает и на движущемся, и на неподвижном. Выключено — показывает как есть, открытым с обеих сторон.':
        'Takes away the far side of the top screen so its own back does not show through the front cells. Works on the moving one and the still one. Off, it shows as it is, open on both sides.',
    'Альфа': 'Alpha',
    'Premultiplied кладёт цвет целиком: то, что осталось под прозрачной альфой, видно, а не умножено на неё, и пиксель, чей цвет ярче собственной альфы, вылетает. На нём и проверяют контент. Straight умножает цвет на альфу — так контент и задуман, и так его покажет стена.':
        'Premultiplied lays the colour down whole: whatever was left under a transparent alpha shows instead of being multiplied by it, and a pixel brighter than its own alpha blows out. It is what content is checked on. Straight multiplies the colour by the alpha: that is how the content is meant, and how the wall will show it.',
    'Фон': 'Backing',
    'Калибровка': 'Calibration',
    'Чёрный': 'Black',
    'Что показывают экраны там, где контент прозрачен или его нет':
        'What the screens show where the content is transparent or missing',
    'Сбросить вид: назад к целому кадру. Двойной щелчок по картинке делает то же; колесо приближает, перетаскивание двигает.':
        'Reset the view: back to the whole frame. A double-click on the picture does the same; the wheel zooms, dragging moves.',
    'Во весь экран': 'Full screen',
    'Выйти  Esc': 'Exit  Esc',
    'Картинка на весь монитор, на котором стоит окно, всё остальное убирается. Ещё раз — обратно, или Escape. F11 делает то же с клавиатуры.':
        'The picture fills the monitor the window is on and everything else goes. Again to come back, or Escape. F11 does the same from the keyboard.',
    'Рамка': 'Frame',
    'Линия, показывающая, что попадёт в запись. Картинка занимает всё окно и продолжается за рамкой; эта линия говорит, где рамка. В Превью и в Инспекторе, где есть что кадрировать.':
        'A line showing what the render will get. The picture fills the window and runs past the frame; this line says where the frame is. In Preview and in Inspection, where there is something to frame.',
    'Плитка': 'Tile',
    'Горизонтальный тайл: каждый экран повторяется лентой без конца, влево и вправо, как он и идёт по кругу здания. Только в Развертке.':
        'Horizontal tiling: each screen repeats as an endless band to the left and right, the way it runs round the building. In Flat only.',
    'Рамка = кадр рендера {0}×{1}': 'Frame = the render\'s {0}×{1}',
    'Рамка выключена': 'Frame off',
    'Как читается левая половина — файл как он есть. Половины выбирают независимо, в этом и смысл: после дизера один и тот же файл, прочитанный любым способом, — одна и та же картинка, и поставить их по-разному и не увидеть разницы это и есть проверка. Переключатель Alpha наверху в этом режиме не действует.':
        'How the left half is read: the file as it is. The halves are chosen apart, and that is the point: after a dither the same file read either way is the same picture, and setting them differently and seeing no difference is the check. The Alpha switch above does nothing in this mode.',
    'Как читается правая половина — то, что из него делает перепечка. Половины выбирают независимо, в этом и смысл: после дизера один и тот же файл, прочитанный любым способом, — одна и та же картинка, и поставить их по-разному и не увидеть разницы это и есть проверка. Переключатель Alpha наверху в этом режиме не действует.':
        'How the right half is read: what the rebake makes of it. The halves are chosen apart, and that is the point: after a dither the same file read either way is the same picture, and setting them differently and seeing no difference is the check. The Alpha switch above does nothing in this mode.',
    'файл': 'file',
    'перепечка': 'rebake',

    # -- the top line ---------------------------------------------------------------------
    'Слои ▾': 'Layers ▾',
    'Какие части здания рисовать': 'Which parts of the building to draw',
    'Проверка машины': 'Machine check',
    'Что есть на этой машине из нужного: видеокарта, ffmpeg, звук. Там же — скачать ffmpeg, если его нет.':
        'What this machine has of what is needed: the graphics card, ffmpeg, sound. It also offers to download ffmpeg if it is missing.',
    'Лог': 'Log',
    'Открыть папку, в которую пишется эта сессия': 'Open the folder this session is logged to',
    'Просмотр': 'Quick look',
    'Быстрый просмотр: по файлу на карточку, все с нулевого кадра. Положил, посмотрел на здании, отрендерил.':
        'The quick look: one file a card, all from frame zero. Put them in, look at them on the building, render.',
    'Шоу': 'Show',
    'Шоу на таймлайне: клипы на своих кадрах, слои, фейды, лупы, кью; правится в редакторе. Без открытого .trix показывает карточки Просмотра как шоу.':
        'A show on a timeline: clips at their frames, layers, fades, loops, cues; edited in the editor. With no .trix open it shows the quick look\'s cards as a show.',
    'Здание через камеру из файла, кадрированное так, как оно будет записано, — на нём и судят контент.':
        'The building through the file\'s camera, framed the way it will be written: the view content is judged on.',
    'Экраны развёрнуты в полосы и сложены стопкой: каждый видно целиком. Рендер здесь пишет каждый экран отдельно.':
        'The screens unrolled into strips and stacked: each one seen whole. A render here writes each screen on its own.',
    'Камера отпущена с этого кадра и летает вокруг здания: тянуть — вращать, колесо — ближе, правая кнопка или Shift — сдвинуть, двойной щелчок — вернуться.':
        'The camera is let go from this frame and flies round the building: drag to orbit, the wheel to come closer, the right button or Shift to pan, a double-click to come back.',
    'Top и Bottom, каждая полоса разрезана посередине: слева файл, справа то, что из него сделает перепечка.':
        'Top and Bottom, each strip cut down the middle: the file on the left, what the rebake will make of it on the right.',
    'Рядом с приложением нет запечённой сцены': 'There is no baked scene beside the application',

    # -- the transport and the status line ---------------------------------------------------
    'кадр 0 из 0': 'frame 0 of 0',
    'кадр {0} из {1}': 'frame {0} of {1}',
    '{0}   кадр {1} из {2}': '{0}   frame {1} of {2}',
    'Где стоит плейхед: кадр на сетке просмотра и сколько их всего':
        'Where the playhead is: the frame on the grid it is watched at, and how many there are',
    'Смотреть по': 'Watch at',
    '{0} к/с': '{0} fps',
    'Сетка, по которой смотрят всю вещь. На неё разом ложится всё — экраны, счётчик кадров, моторы, — так что вещь на тридцати кадрах смотрится по кадру, а не выбирается дважды на каждый свой кадр. С какой частотой писать, выбирается в строке рендера.':
        'The grid the whole piece is watched at. Everything lands on it at once (the screens, the frame counter, the motors), so a piece at thirty frames is watched frame by frame rather than picked twice for each of its frames. The rate to write at is chosen on the render line.',
    'Статистика декодера ▴': 'Decoder stats ▴',
    'Статистика декодера {0}': 'Decoder stats {0}',
    'Счётчики чтения по каждому файлу: сколько прочитано, выброшено, пропущено. Для случая, когда что-то дёргается. Состояние запоминается.':
        'The reading counts for each file: how many frames were read, dropped, skipped. For when something stutters. Remembered between sessions.',
    'рисует {0:4.1f} к/с · {1:.2f} мс на кадр': 'drawing {0:4.1f} fps · {1:.2f} ms a frame',
    'стоит · последний кадр {0:.2f} мс': 'still · last frame {0:.2f} ms',
    '{0} · камера {1}': '{0} · camera {1}',
    'файлы: {0}': 'files: {0}',
    'файлов нет': 'no files',
    ' · выброшено кадров {0}': ' · frames dropped {0}',
    '{0:26s} {1:5d}x{2:<5d} прочитано {3:6d}  выброшено {4:5d}  пропущено {5:5d}  ждали {6:5d}  демукс {7:5.2f}  распаковка {8:5.2f} мс':
        '{0:26s} {1:5d}x{2:<5d} read {3:6d}  dropped {4:5d}  skipped {5:5d}  waited {6:5d}  demux {7:5.2f}  unpack {8:5.2f} ms',
    '   в конце': '   at the end',

    # -- the render line -------------------------------------------------------------------------
    'Рендер': 'Render',
    'Кадры': 'Frames',
    'Первый записываемый кадр. Считается так же, как счётчик у плейхеда, по сетке просмотра. Shift+I и Shift+O ставят начало и конец туда, где плейхед.':
        'The first frame to write. Counted the way the playhead\'s counter is, on the grid it is watched at. Shift+I and Shift+O put the start and the end where the playhead is.',
    'Последний записываемый кадр, он сам включительно. Считается так же, как счётчик у плейхеда, по сетке просмотра. Shift+I и Shift+O ставят начало и конец туда, где плейхед.':
        'The last frame to write, that one included. Counted the way the playhead\'s counter is, on the grid it is watched at. Shift+I and Shift+O put the start and the end where the playhead is.',
    'всё': 'all',
    'Всю вещь целиком': 'The whole piece',
    'С какой частотой писать файл': 'The frame rate to write the file at',
    'Папка, в которую писать: впишите путь или выберите «Куда…». Папки, которой ещё нет, при записи будет создана.':
        'The folder to write into: type a path or choose Where…. A folder that is not there yet is made when writing.',
    'Как будет называться файл. Расширение следует за форматом слева и подставляется, если его не написать. Загрузите Что-то_top и Что-то_bottom — и имя составится само.':
        'What the file will be called. The extension follows the format on the left and is added if it is left off. Load Something_top and Something_bottom and the name makes itself.',
    'Папка — это полный путь, например D:\\Renders; осталась прежняя':
        'A folder is a whole path, like D:\\Renders; the old one stays',
    'Куда…': 'Where…',
    'Папка, в которую писать, и как назвать файл': 'The folder to write into, and what to call the file',
    'Следующая версия': 'Next version',
    'Ничего никогда не перезаписывается; это находит следующее свободное имя: _v1 становится _v2.':
        'Nothing is ever written over; this finds the next free name: _v1 becomes _v2.',
    'Снимок': 'Snapshot',
    'Снимок кадра': 'Snapshot of the frame',
    'Записать этот один кадр в PNG, рядом с тем, куда идёт видео. В Превью это та же картинка, что записал бы рендер, в выбранном размере; в Развертке — каждый экран отдельно, в его родном размере.':
        'Write this one frame to a PNG beside where the video goes. In Preview it is the same picture a render would write, at the chosen size; in Flat, each screen on its own at its native size.',
    'Снимать нечего: ничего не загружено': 'Nothing to take: nothing is loaded',
    'Снимок: {0}/{1}': 'Snapshot: {0}/{1}',
    ' и ещё {0}': ' and {0} more',
    'Снимок не записан: {0}': 'Snapshot not written: {0}',
    'Стоп': 'Stop',
    'Остановить рендер': 'Stop the render',
    'Записанное к этому моменту выбрасывается.': 'What has been written so far is thrown away.',
    'Открыть папку': 'Open folder',
    'Открыть папку с записанным': 'Open the folder with what was written',
    'Записать весь диапазон, все экраны разом, в файл, названный слева. Вид сперва возвращается к целому кадру, так что записывается именно то, что в кадре.':
        'Write the whole range, every screen at once, to the file named on the left. The view goes back to the whole frame first, so what is written is exactly what is in the frame.',
    'Полный': 'Full',
    'Каждый экран пишется в своём собственном разрешении — столько пикселей, сколько у стены на самом деле. Половина и четверть считаются от него же и округляются вниз до кратного четырём, иначе кодировщик не возьмёт кадр.':
        'Each screen is written at its own resolution, as many pixels as the wall really has. Half and quarter are counted from that and rounded down to a multiple of four, or the encoder will not take the frame.',
    '{0} из {1}   {2:.1f} к/с   осталось {3:.0f} с': '{0} of {1}   {2:.1f} fps   {3:.0f} s left',
    'Записано: {0} кадров за {1:.0f} с ({2:.1f} к/с)': 'Written: {0} frames in {1:.0f} s ({2:.1f} fps)',
    'Нечего записывать: ничего не загружено': 'Nothing to write: nothing is loaded',
    '{0} уже есть — уберите его или смените имя': '{0} is there already: move it away or change the name',
    'Видео записать нечем: не найден ffmpeg': 'No way to write video: ffmpeg was not found',
    '{0} уже есть — нажмите +1, чтобы записать следующей версией':
        '{0} is there already: press +1 to write the next version',
    'Остановлено': 'Stopped',
    'Не записано: ': 'Not written: ',

    # -- the file dialogs -----------------------------------------------------------------------------
    'Выбрать JSON моторов': 'Choose a motor JSON',
    'Моторы (*.json);;Все файлы (*)': 'Motors (*.json);;All files (*)',
    'Выбрать WAV': 'Choose a WAV',
    'Звук (*.wav);;Все файлы (*)': 'Sound (*.wav);;All files (*)',
    'Выбрать ролик или картинку': 'Choose a movie or a picture',
    'Ролики и картинки (*.mov *.mp4 *.m4v *.mkv *.avi *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga);;Ролики (*.mov *.mp4 *.m4v *.mkv *.avi);;Картинки (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga);;Все файлы (*)':
        'Movies and pictures (*.mov *.mp4 *.m4v *.mkv *.avi *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga);;Movies (*.mov *.mp4 *.m4v *.mkv *.avi);;Pictures (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp *.tga);;All files (*)',

    # -- the rebake ------------------------------------------------------------------------------------
    'Чистка': 'Clean',
    'Дизер': 'Dither',
    'Дизер превращает альфу в одни только 0 и 255 по неподвижной карте голубого шума и уводит цвет вместе с ней — после этого два чтения файла не могут различаться вовсе. Чистка альфу не трогает и стирает цвет там, где альфа ниже порога: фейд остаётся фейдом, а худшее из того, что показывает премультиплаед, уходит.':
        'Dither turns the alpha into nothing but 0 and 255 by a fixed blue-noise map and takes the colour with it; after that the two readings of the file cannot differ at all. Clean leaves the alpha alone and wipes the colour where the alpha is below the threshold: a fade stays a fade, and the worst of what premultiplied shows goes.',
    'порог': 'below',
    'Чистка стирает цвет под любой альфой ниже этого значения, в том счёте, в каком ведёт его файл, от 0 до 255. Восьмёрка не отличима от прозрачного: убирает грязь и оставляет фейд.':
        'Clean wipes the colour under any alpha below this value, counted the way the file counts it, 0 to 255. Eight cannot be told from transparent: it takes the dirt away and leaves the fade.',
    'цвет': 'colour',
    'Умножить': 'Multiply',
    'Оставить': 'Keep',
    'Прижать': 'Clamp',
    'Что происходит с цветом выше порога. «Оставить» — фейд ровно такой, каким он сделан. «Прижать» прижимает каждый канал к его собственной альфе: вспышка уходит, но появляется излом — канал либо не тронут, либо срезан. «Умножить» вместо этого сворачивает цвет с его альфой; это масштаб, а не потолок, поэтому излома нет нигде: премультиплаед становится верным чтением, а стрэйт расплачивается тем, что применяет альфу второй раз.':
        'What happens to the colour above the threshold. Keep: the fade exactly as it was made. Clamp holds each channel down to its own alpha: the flare goes, but a kink appears, since a channel is either untouched or cut. Multiply instead folds the colour with its alpha; that is a scale rather than a ceiling, so there is no kink anywhere: premultiplied becomes the right reading, and straight pays by applying the alpha a second time.',
    'в': 'as',
    'Hap Q Alpha — тот самый формат, в котором лежат исходники, поэтому перепечённый файл встаёт ровно туда, где был старый. ffmpeg его не пишет: у его кодировщика Hap нет формата с отдельным слоем альфы, — поэтому цвет жмёт ffmpeg как Hap Q, это те же блоки YCoCg, а альфу и обёртку делает вьювер. ProRes 4444 — второй вариант, для мест, где нужен обычный промежуточный файл.':
        'Hap Q Alpha is the very format the sources are in, so the rebaked file drops in exactly where the old one was. ffmpeg does not write it, since its Hap encoder has no format with a separate alpha plane, so ffmpeg compresses the colour as Hap Q (the same YCoCg blocks) and the viewer makes the alpha and the wrapper. ProRes 4444 is the second choice, for places that want an ordinary intermediate file.',
    'Скачать ffmpeg, который умеет': 'Download an ffmpeg that can',
    'Здесь нет кодировщика, который нужен этому формату. Это скачает сборку, которая его умеет, и положит рядом с приложением: ничего не устанавливается, ничего не прописывается в PATH, а удаление папки отменяет всё.':
        'The encoder this format needs is not here. This downloads a build that has it and puts it beside the application: nothing is installed, nothing goes into PATH, and deleting the folder undoes it all.',
    'Проба': 'Probe',
    'Записать кадр, на котором стоит таймлайн, оба экрана, в PNG в натуральную величину файла. Зерно шириной в один пиксель, а полосы наверху — нет, так что это единственный честный на него взгляд.':
        'Write the frame the timeline is on, both screens, to PNGs at the file\'s own size. The grain is a pixel wide and the strips above are not, so this is the only honest look at it.',
    'Перепечь': 'Rebake',
    'Записать оба экрана целиком, в их собственном размере и частоте, в выбранном рядом формате. В Hap Q Alpha готовый файл забирает имя исходника, а исходник отходит с суффиксом _old: всё, что на эти файлы ссылалось, продолжает работать и показывает уже перепечённое, и ничего не удаляется. В ProRes файл ложится рядом с исходником с суффиксом _prores, а исходник остаётся нетронутым.':
        'Write both screens whole, at their own size and rate, in the format chosen beside. In Hap Q Alpha the finished file takes the source\'s name and the source steps aside with _old: everything that pointed at those files keeps working and now shows the rebake, and nothing is deleted. In ProRes the file goes beside the source with _prores, and the source is left alone.',
    'Остановить перепечку. Половина файла хуже, чем ничего, поэтому записанное удаляется.':
        'Stop the rebake. Half a file is worse than none, so what was written is deleted.',
    'строю карту порогов…': 'building the threshold map…',
    'качаю ffmpeg…': 'downloading ffmpeg…',
    'не скачалось: {0}': 'the download failed: {0}',
    'качаю ffmpeg: {0:.0f} из {1:.0f} МБ': 'downloading ffmpeg: {0:.0f} of {1:.0f} MB',
    'качаю ffmpeg: {0:.0f} МБ': 'downloading ffmpeg: {0:.0f} MB',
    'готово — в этом кодировщик есть': 'done: this one has the encoder',
    'ни в одном ffmpeg здесь нет кодировщика {0}': 'no ffmpeg here has the {0} encoder',
    'пробовать нечего: ничего не загружено': 'nothing to probe: nothing is loaded',
    'проба не удалась: {0}': 'the probe failed: {0}',
    'ни у одного экрана здесь нет альфы': 'none of the screens here has an alpha',
    'перепекать нечего: ничего не загружено': 'nothing to rebake: nothing is loaded',
    'перепечь нечем: не найден ffmpeg': 'nothing to rebake with: ffmpeg was not found',
    '{0} уже есть — уберите его': '{0} is there already: move it away',
    'перепекаю…': 'rebaking…',
    'остановлено': 'stopped',
    'записано: ': 'written: ',
    'записано, но не встало на место — ': 'written, but not put in place: ',
    'на месте: {0}; прежние оставлены как ': 'in place: {0}; the old kept as ',

    # -- the keys card ------------------------------------------------------------------------------------
    'Пробел': 'Space',
    'играть / пауза': 'play / pause',
    'кадр назад / вперёд': 'a frame back / on',
    'секунда назад / вперёд': 'a second back / on',
    'в начало / в конец': 'to the start / the end',
    'на начало / конец клипа': 'to the clip\'s start / end',
    'отпустить луп / держать': 'let the loop go / hold it',
    'вся длина': 'the whole length',
    'начало / конец рендера здесь': 'the render starts / ends here',
    'эта подсказка': 'this card',
    'ЛКМ': 'Left',
    'выбрать клип': 'choose a clip',
    'ПКМ': 'Right',
    'прокрутка': 'scroll',
    'СКМ': 'Middle',
    'плейхед сюда': 'the playhead here',
    'колесо': 'wheel',
    'зум, с Shift — прокрутка': 'zoom; with Shift, scroll',
    '\n\nредактор\n': '\n\nthe editor\n',
    'отменить / вернуть': 'undo / redo',
    'удалить клип': 'delete the clip',
    'клип концом / началом к плейхеду': 'the clip\'s end / start to the playhead',
    'луп на весь клип': 'a loop over the whole clip',
    'замок лупов': 'the loops\' lock',
    'тащить клип': 'drag a clip',
    'по времени и по уровням; Alt — без прилипания': 'in time and across levels; Alt, no snapping',
    'тащить по лупам': 'drag on the loops',
    'новый луп; за край — край; Shift — целиком': 'a new loop; by an edge, that edge; Shift, the whole',
    'файл на дорожку': 'a file onto a lane',
    'клип там, где отпустили': 'a clip where it is let go',
    'во весь экран и обратно': 'full screen and back',
    'приблизить кадр': 'zoom into the frame',
    'тащить': 'drag',
    'сдвинуть кадр; в Инспекторе — облёт': 'move the frame; in Inspection, orbit',
    'двойной щелчок': 'double-click',
    'вернуть вид': 'reset the view',

    # -- the clip, the loops, the lanes ------------------------------------------------------------------------
    'Клип': 'Clip',
    'Экраны': 'Screens',
    'Лупы': 'Loops',
    'Звук': 'Sound',
    'Уровень': 'Level',
    'Кадр начала': 'Starts at',
    'Подрезка с головы': 'Head trim',
    'Подрезка с хвоста': 'Tail trim',
    'Фейд с головы': 'Fade in',
    'Фейд с хвоста': 'Fade out',
    'Длина': 'Length',
    'Занимает': 'Occupies',
    'Команды': 'Commands',
    'Начинается': 'Begins',
    'Кадр': 'At frame',
    'Время': 'Time',
    'Диапазон рендера — этот клип': 'Render range = this clip',
    'Поставить начало и конец рендера на края выбранного клипа':
        'Put the render\'s start and end on the chosen clip\'s edges',
    'клип не выбран': 'no clip chosen',
    'картинка': 'picture',
    'кью на кадре {0}': 'cue at frame {0}',
    '   (нет файла)': '   (no file)',
    '{0:.2f} с': '{0:.2f} s',
    ' · фейд {0:.1f} с': ' · fade {0:.1f} s',
    ' · фейд вход {0:.1f} с': ' · fade in {0:.1f} s',
    'кью  кадр {0}  universe {1}  channel {2}  value {3}':
        'cue  frame {0}  universe {1}  channel {2}  value {3}',
    '\nфайла нет на этой машине': '\nthe file is not on this machine',
    '  — нет файла': '  (no file)',
    'Загорается сам, когда плейхед въезжает в луп слева: с этого момента луп держит. Нажми, чтобы отпустить — плейхед поедет дальше, до следующего лупа (L).':
        'Lights by itself when the playhead runs into a loop from the left: from then on the loop holds. Press to let go, and the playhead goes on to the next loop (L).',
    '{0} · кадр {1}': '{0} · frame {1}',
    'замок': 'locked',
    'открыто': 'open',
    'Запретить рисовать лупы мышью (K). Числами справа их всё равно можно поправить — на 22 минутах один пиксель это 56 кадров.':
        'Stop loops being drawn with the mouse (K). They can still be set in numbers on the right: on 22 minutes a pixel is 56 frames.',
    'лупы': 'loops',
    'лупов нет': 'no loops',
    '{0} из {1} · {2:.1f} с': '{0} of {1} · {2:.1f} s',
    ' · держит': ' · holding',
    ' · отпущен': ' · let go',
    '{0} {1}  с {2}  по {3}': '{0} {1}  from {2}  to {3}',
    'с': 'from',
    'по': 'to',
    'Ещё один луп с того кадра, где плейхед.': 'One more loop, from the playhead\'s frame.',
    'Убрать выбранный луп.': 'Remove the chosen loop.',
    'по клипу': 'to clip',
    'Луп на весь выбранный клип, и держать (Shift+L).':
        'A loop over the whole chosen clip, and hold it (Shift+L).',
    'из файла': 'from file',
    'Вернуть лупы, с которыми шоу открылось.': 'Bring back the loops the show opened with.',
    'на экранах: ': 'on screens: ',
    'ничего': 'nothing',
    'В ЛУПЕ   ': 'IN LOOP   ',
    'поле {0}': 'field {0}',
    'кью': 'cue',
    'луп числами': 'loop in numbers',
    'новый луп': 'new loop',
    'луп мышью': 'loop with the mouse',
    'перенос клипа': 'move a clip',
    'клип к плейхеду': 'clip to the playhead',
    'убрать луп': 'remove a loop',
    'луп по клипу': 'loop to the clip',
    'лупы из файла': 'loops from the file',
    'лупы заперты — «замок» справа на полосе или K':
        'the loops are locked: the lock at the right of the strip, or K',
    'бросать файлы на дорожки — в редакторе': 'files are dropped onto lanes in the editor',
    '{0} не берёт {1} — ролики и картинки на экраны, .wav на Sound, .json на Kinetic':
        '{0} does not take {1}: movies and pictures go on the screens, .wav on Sound, .json on Kinetic',

    # -- what the files are ---------------------------------------------------------------------------------------
    'видео': 'video',
    '{0}  {1} · лупы {2}': '{0}  {1} · loops {2}',
    ' · нет на машине {0}': ' · not on this machine {0}',
    '{0} — это не файл шоу': '{0} is not a show file',
    '{0}: такого файла нет': '{0}: no such file',
    '{0}моторов {1}  кадров {2}  {3:g} к/с  {4:.2f} с':
        '{0}motors {1}  frames {2}  {3:g} fps  {4:.2f} s',
    'файлов {0}  ': 'files {0}  ',
    'проходов {0}  ': 'passes {0}  ',
    'часть {0} из {1}; нет {2}': 'part {0} of {1}; {2} missing',
    'части не по порядку: ': 'parts out of order: ',
    '{0:g} кГц  {1}  {2:.2f} с': '{0:g} kHz  {1}  {2:.2f} s',
    'звуков в смеси {0}  {1:g} кГц  {2}  {3:.2f} с': 'sounds in the mix {0}  {1:g} kHz  {2}  {3:.2f} s',
    '{0} кан.': '{0} ch.',
    'моно': 'mono',
    'стерео': 'stereo',
    '{0:.1f} м, {1:.0f}° по кругу, {2:+.0f}° вверх': '{0:.1f} m, {1:.0f}° round, {2:+.0f}° up',

    # -- what the machine has -----------------------------------------------------------------------------------------
    'поставьте ffmpeg менеджером пакетов, например apt install ffmpeg':
        'install ffmpeg with the package manager, for example apt install ffmpeg',
    'в комплекте': 'bundled',
    'рядом с программой': 'beside the program',
    'texture-compression-bc — блоки идут прямо в сэмплер':
        'texture-compression-bc: the blocks go straight to the sampler',
    'этой видеокарте недоступно ({0}), поэтому блоки распаковывает вычислительный проход — меньше миллисекунды на кадр':
        'not available on this card ({0}), so a compute pass unpacks the blocks, under a millisecond a frame',
    'нет такой возможности': 'no such feature',
    'ничего нельзя записать': 'nothing can be written',
    'в этом нет кодировщика hap — ему нужна сборка со snappy. Смотреть и рендерить это не мешает, а перепечке в Hap Q Alpha он нужен. «Скачать» принесёт сборку, в которой он есть.':
        'this one has no hap encoder, which needs a build with snappy. Watching and rendering do not mind; a rebake to Hap Q Alpha needs it. Download fetches a build that has it.',
    'перепечка сможет писать только ProRes': 'the rebake can write ProRes only',
    'он нужен только чтобы записывать видео; смотреть можно и без него':
        'it is needed only to write video; watching works without it',

    # -- the kinetic editor ---------------------------------------------------
    'Подъём': 'Lift',
    'Вынос': 'Push',
    'Наклон': 'Tilt',
    'Кисть': 'Brush',
    'Выбор': 'Select',
    'Профиль': 'Profile',
    'к ключу назад / вперёд': 'to the key before / after',
    'ключ всем моторам слоя': 'key every motor of the layer',
    'ключ всем моторам всех слоёв': 'key every motor of every layer',
    'удалить выбранные ключи': 'delete the chosen keys',
    'копировать позу слоя / вставить на плейхед':
        "copy the layer's pose / paste it at the playhead",
    'слой: подъём, вынос, наклон': 'layer: lift, push, tilt',
    'видео или маска': 'video or mask',
    'ПКМ по 3D': 'RMB on the 3D',
    'облёт; СКМ или Shift — сдвиг; колесо — ближе':
        'orbit; MMB or Shift to slide; the wheel comes closer',
    'Открыто: {0}': 'Opened: {0}',
    'Записан {0}': 'Wrote {0}',
    'К следующему ключу, где наклон вне предела':
        'To the next key where a tilt is past its limit',
    ' с': ' s',
    'без имени': 'untitled',
    'Поза слоя «{0}» скопирована': 'The {0} pose is copied',
    'кольцо {0}, сота {1}: зазор под ним {2}, вынос {3:.0f} мм, наклон {4:+.1f}° (вниз до {5:.0f}°, вверх до {6:.0f}°)':
        'ring {0}, cell {1}: gap under it {2}, push {3:.0f} mm, tilt {4:+.1f}° (down to {5:.0f}°, up to {6:.0f}°)',
    'Сохранить изменения в кинетике?': 'Save the changes to the kinetics?',
    'Открыть кинетику': 'Open kinetics',
    'Кинетика (*.kin *.json)': 'Kinetics (*.kin *.json)',
    'Сохранено: {0}': 'Saved: {0}',
    'Экспорт моторного JSON': 'Export the motor JSON',
    'Моторный JSON (*.json)': 'Motor JSON (*.json)',
    'Видео на соты': 'A video for the cells',
    'Видео и картинки (*.mov *.mp4 *.png *.jpg *.jpeg *.tif *.tiff)':
        'Videos and pictures (*.mov *.mp4 *.png *.jpg *.jpeg *.tif *.tiff)',
    'Видео: {0}': 'Video: {0}',
    'Звук (*.wav)': 'Sound (*.wav)',
    'Звук: {0}': 'Sound: {0}',
    'Нет 3D: {0}': 'No 3D: {0}',
    'Новый': 'New',
    'Пустая кинетика': 'Empty kinetics',
    'Открыть…': 'Open…',
    'Проект редактора (.kin) или моторный JSON':
        'An editor project (.kin) or a motor JSON',
    'Сохранить': 'Save',
    'Экспорт JSON…': 'Export JSON…',
    'Моторный JSON для вьюера и площадки, Ctrl+E':
        'The motor JSON for the viewer and the site, Ctrl+E',
    'Видео…': 'Video…',
    'HAP или картинка на соты': 'HAP or a picture on the cells',
    'Звук…': 'Sound…',
    'Видео': 'Video',
    'Маска': 'Mask',
    'Во вьюере…': 'In the viewer…',
    'Сохранить JSON и открыть его во вьюере — вместо того, что загружено во вьюере сейчас':
        'Save the JSON and open it in the viewer, in place of what the viewer has loaded now',
    'Вид': 'View',
    'Вернуть камеру': 'Put the camera back',
    'Ключ': 'Key',
    'K: ключ всем моторам слоя на плейхеде':
        'K: key every motor of the layer at the playhead',
    'Ключ всем': 'Key all',
    'Shift+K: ключ всем моторам всех слоёв': 'Shift+K: key every motor of every layer',
    'Удалить ключи': 'Delete keys',
    'Delete: выбранные ключи на таймлайне': 'Delete: the keys chosen on the timeline',
    '◀ ключ': '◀ key',
    'ключ ▶': 'key ▶',
    'кадр {0}': 'frame {0}',
    'Сначала выберите соты': 'Choose some cells first',
    'Выберите ключи на таймлайне': 'Choose keys on the timeline',
    'Выбрано ключей: {0}': 'Keys chosen: {0}',
    'Сохранить кинетику': 'Save kinetics',
    'Проект кинетики (*.kin)': 'Kinetics project (*.kin)',
    'наклон вне предела на {0} ключах': 'tilt past its limit at {0} keys',
    'Вне предела: {0}': 'Past the limit: {0}',
    'Видео не открылось: {0}': 'The video did not open: {0}',
    'Звук не открылся: {0}': 'The sound did not open: {0}',
    'Красить': 'Paint',
    'Сгладить': 'Smooth',
    'Стереть': 'Erase',
    'Сота': 'Cell',
    'Группа': 'Group',
    'Кольцо': 'Ring',
    'мм': 'mm',
    'сот': 'cells',
    'Наклон по касательной': 'Tilt along the tangent',
    'Размер': 'Size',
    'Жёсткость': 'Hardness',
    'Сила': 'Strength',
    'Щелчок берёт': 'A click takes',
    'Всё': 'All',
    'Снять': 'None',
    'Обратить': 'Invert',
    'Авторотейт': 'Auto-rotate',
    'Как rotate_auto в Houdini: каждая сота ложится вдоль поверхности, которую сейчас составляют подъём и вынос, в пределах своих зазоров. Без выбора — все соты. 100 % — ровно по поверхности.':
        "As Houdini's rotate_auto: each cell lies along the surface the lift and the push make now, within its gaps. With nothing chosen, every cell. 100 % lies exactly along the surface.",
    'Профиль вазы': 'Vase profile',
    '{0}: кадр {1}, моторов {2} из {3}': '{0}: frame {1}, {2} motors of {3}',
    'Кисть {0:.1f} соты': 'Brush {0:.1f} cells',
    '{0}: {1:g} к/с, а редактор работает в {2} к/с':
        '{0}: {1:g} fps, and the editor works at {2} fps',
    'ключей домкратов между положениями: {0}': 'jack keys between positions: {0}',
    'моторов с наложенными сегментами: {0}': 'motors with overlapping segments: {0}',
    'моторов, где сегмент начат не с места мотора: {0}':
        'motors with a segment starting away from the motor: {0}',
    'сот вне предела наклона: {0} на {1} ключах':
        'cells past the tilt limit: {0} at {1} keys',
    '{0} — не проект редактора кинетики': '{0} is not a kinetic editor project',
    '{0}: ключ не того размера': '{0}: a key of the wrong size',
    'домкрат ряда 1 двигается, а у машины его нет — файл пронумерован как в Houdini, подъём сдвинут на кольцо':
        'the row 1 jack moves, and the machine has none: the file is numbered as Houdini numbers it, the lift is one ring off',
    'Моторы': 'Motors',
    'Ключи': 'Keys',
    'Симуляция': 'Simulation',
    'Оба': 'Both',
    'Что на сотах: ключи, как их сыграют моторы, или оба — второе призраком':
        'What the cells show: the keys, the motors playing them, or both, the second as a ghost',
    'Изнанка': 'Backs',
    'Показывать задние стороны сот, чёрные, — выключает отсечение задних граней':
        'Show the backs of the cells, black; turns backface culling off',
    'Симуляция перенесена в ключи': 'The simulation is now the keys',
    'Моторы: пропущено команд {0}, опоздали ходов {1}, наклон сверх зазоров на {2} кадрах — «Перенести в ключи» в панели «Моторы»':
        'Motors: {0} commands dropped, {1} moves late, tilt past the gaps on {2} frames; see Motors to put the simulation onto the keys',
    'моторы пропустят команд: {0}': 'the motors will drop {0} commands',
    'Перенести симуляцию в ключи': 'Put the simulation onto the keys',
    'Как их считает Cinema 4D: ход не быстрее мотора — полный ход за столько секунд, половина за половину; после каждого хода отдых; команда, пришедшая во время хода или отдыха, пропускается.':
        'As Cinema 4D reckons them: no move faster than the motor, a full travel in so many seconds and half of one in half; a rest after every move; a command arriving during a move or a rest is dropped.',
    'ход, с': 'travel, s',
    'отдых, с': 'rest, s',
    'Призраком в «Оба»': 'The ghost in Both',
    'Ключи встанут там, где моторы на самом деле начинают и заканчивают ход; пропущенные команды уйдут. Экспорт после этого — то, что сыграет площадка. Отменяется Ctrl+Z.':
        'The keys go where the motors really start and finish their moves; the dropped commands go. The export is then what the site will play. Ctrl+Z undoes it.',
    'Симуляция считается…': 'Simulating…',
    'Простой': 'Simple',
    'Подробный': 'Detailed',
    'Кольцо {0}': 'Ring {0}',
    'Группа {0} · соты {1}–{2}': 'Group {0} · cells {1}–{2}',
    'Сота {0}': 'Cell {0}',
    '{0}: ключей {1}, кадры {2}–{3}': '{0}: {1} keys, frames {2}–{3}',
    'выбор: кольца, группы, соты': 'selection: rings, groups, cells',
    'кольца': 'rings',
    'группы': 'groups',
    'отдельные соты': 'single cells',
    'Выбор: {0}': 'Selection: {0}',
    'ПКМ по карте': 'RMB on the map',
    'сдвиг; колесо — ближе; двойной ПКМ — вся карта':
        'slide; the wheel zooms; double RMB shows the whole map',
    'Слой, с которым работаем: Q, W, E': 'The layer being worked on: Q, W, E',
    'Все три слоя в цветах Houdini: R подъём, G вынос, B наклон; иначе — только слой, с которым работаем':
        "All three layers in Houdini's colours: R lift, G push, B tilt; otherwise only the layer being worked on",
    'Поза «{0}» сохранена': 'Pose "{0}" saved',
    'Поза «{0}» поставлена на кадр {1}': 'Pose "{0}" keyed at frame {1}',
    'Имя позы:': 'Pose name:',
    'Сначала сохраните позу': 'Save a pose first',
    'Ключ выбранным моторам слоя там, где они стоят':
        "Key the layer's chosen motors where they stand",
    'кадр {0} · {1} · {2} · опоздал на {3:.1f} с':
        'frame {0} · {1} · {2} · {3:.1f} s late',
    'разные: {0:+.1f}…{1:+.1f}° · ': 'mixed: {0:+.1f}…{1:+.1f}° · ',
    'Позы': 'Poses',
    'Только выбранное': 'Only the chosen',
    'Кисть красит лишь выбранные соты, как paint по группе в Houdini':
        'The brush paints only the chosen cells, as Houdini paints on a group',
    'Кисть · {0}': 'Brush · {0}',
    '3 — соты, 2 — группы, 1 — кольца': '3 cells, 2 groups, 1 rings',
    'Пропущено {0} · опоздали {1} · наклон сверх зазоров на {2} кадрах':
        '{0} dropped · {1} late · tilt past the gaps on {2} frames',
    'кадр {0} · наклон сверх зазоров · сот {1}':
        'frame {0} · tilt past the gaps · {1} cells',
    'кольцо {0}': 'ring {0}',
    'кольцо {0}, мотор {1}': 'ring {0}, motor {1}',
    'кадр {0} · {1} · {2} · команда пропущена':
        'frame {0} · {1} · {2} · command dropped',
    'Ничего не выбрано — 1 кольца, 2 группы, 3 соты':
        'Nothing chosen: 1 rings, 2 groups, 3 cells',
    'Выбрано: колец {0} · групп {1} · сот {2}':
        'Chosen: {0} rings · {1} groups · {2} cells',
    'разные: {0:.0f}–{1:.0f} мм': 'mixed: {0:.0f}–{1:.0f} mm',
    'можно: вниз до {0:.0f}°, вверх до {1:.0f}°':
        'allowed: down to {0:.0f}°, up to {1:.0f}°',
    'Поставить': 'Put',
    'Ключ позой на плейхеде: выбранным сотам или всем':
        'Key the pose at the playhead: on the chosen cells, or all of them',
    'Сохранить, как стоит сейчас': 'Save it as it stands now',
    'Убрать позу из библиотеки': 'Take the pose out of the library',
    'Вес: положение домкрата, мм': 'Weight: jack position, mm',
    'Вес: вынос, мм': 'Weight: push, mm',
    'Вес: наклон, градусы': 'Weight: tilt, degrees',
    'Ключ ставится только тем моторам, которых коснулась кисть. Пушер слушается самой закрашенной из своих пяти сот, домкрат — кольца, закрашенного больше чем наполовину. Ctrl+колесо — размер.':
        'Only the motors the brush touched get a key. A pusher answers to the most painted of its five cells, a jack to a ring painted over more than half. Ctrl+wheel sets the size.',
    'Щелчок — выбрать, рамка — несколько, Shift — добавить, Ctrl — убрать. Значения выбранного — в блоке «Выбрано» наверху.':
        'Click to choose, draw a box for several, Shift adds, Ctrl takes away. The values of what is chosen are in Chosen at the top.',
    'Кривая — рядом с картой, кольцо к кольцу: насколько вынесено каждое кольцо, все десять его пушеров разом; с выбором — только выбранные группы. Двойной щелчок — точка, правый — убрать.':
        'The curve stands beside the map, ring for ring: how far out each ring is pushed, all ten of its pushers at once; with a selection, only the chosen groups. Double-click adds a point, right click takes one away.',
    '…и ещё {0}': '…and {0} more',
    'Ручки': 'Handles',
    'Ручки выбранного в 3D (T): у кольца — подъём, вынос и наклон, у группы — вынос и наклон, у соты — наклон. Shift — всем выбранным':
        "Handles on what is chosen, in 3D (T): a ring's lift, push and tilt, a group's push and tilt, a cell's tilt. Shift moves every one chosen",
    'тянуть вынос, наклон, подъём выбранного; щелчок — принять, Esc — отменить':
        'pull the chosen push, tilt, lift; click to take it, Esc to put it back',
    'ручки выбранного в 3D; Shift — всем выбранным':
        'handles on what is chosen, in 3D; Shift for all of it',
    '{0}: {1} — щелчок принять, Esc отменить':
        '{0}: {1}; click to take it, Esc to put it back',
    'Отменено': 'Put back',
    # -- masks and primitives -------------------------------------------------
    'Примитивы': 'Primitives',
    'Маска {0}': 'Mask {0}',
    'Сфера {0}': 'Sphere {0}',
    'Куб {0}': 'Box {0}',
    '{0}: щелчок по карте или по 3D ставит его туда':
        '{0}: a click on the map or in 3D puts it there',
    'Примитивы запечены в ключи: {0}; сами выключены':
        'Primitives baked into the keys: {0}; they are turned off',
    'Маска «{0}»: сот {1} — правки только в ней':
        'Mask “{0}”: {1} cells; edits keep to it',
    'Маска «{0}» пустая — нарисуйте её кистью: «Кисть красит: Маску»':
        'Mask “{0}” is empty: paint it with the brush, “Brush paints: Edit mask”',
    'Правки только в маске «{0}»': 'Edits only inside mask “{0}”',
    'Правки — на всех сотах': 'Edits reach every cell',
    'Сначала выберите маску': 'Choose a mask first',
    'На этом кадре нет ключа примитива, который можно снять':
        'No key of the primitive on this frame to take away',
    'Нет включённых примитивов': 'No primitive is on',
    'Сначала добавьте примитив': 'Add a primitive first',
    'Вне маски «{0}» — ничего не изменилось': 'Outside mask “{0}”: nothing changed',
    '{0}: маска не того размера': '{0}: a mask of the wrong size',
    'Маску': 'Edit mask',
    'все соты': 'all cells',
    'Позитив': 'Positive',
    'Негатив': 'Negative',
    'как у действия': 'as it acts',
    'Маску — кисть рисует маску правки: красить добавляет, стереть убирает; без маски сначала заводится новая':
        'Edit mask: the brush paints the mask edits keep to; paint adds, erase takes away; with no mask a new one is made first',
    'Маска правки: всё, что делается на плейхеде — кисть, значения, ручки, G R H, позы, профиль, K, — касается только её сот':
        'The edit mask: everything done at the playhead (brush, values, handles, G R H, poses, profile, K) touches only its cells',
    'Удалить примитив': 'Delete the primitive',
    'Позитив выталкивает соты на свою поверхность — выпуклость; негатив вдавливает их до своей поверхности — отпечаток':
        'Positive pushes the cells out to its surface, a bulge; negative presses them in to its surface, an imprint',
    'Вкл': 'On',
    'Наклон по нормали': 'Tilt along the normal',
    'Задетые соты ложатся вдоль поверхности примитива, насколько позволяют зазоры':
        "The cells it touches lie along the primitive's surface, as far as their gaps allow",
    '◆ Ключ': '◆ Key',
    'Ключ примитиву на плейхеде, там, где он сейчас':
        'Key the primitive at the playhead, where it is now',
    'Снять ключ': 'Remove key',
    'Убрать ключ примитива на плейхеде': "Take away the primitive's key at the playhead",
    'кадров': 'frames',
    'Запечь примитивы в ключи': 'Bake primitives into keys',
    'Что делают включённые примитивы — в ключи моторов, а сами они выключаются. Отменяется Ctrl+Z.':
        "What the primitives that are on do goes into the motors' keys, and they are turned off. Ctrl+Z undoes it.",
    'Кисть красит': 'Brush paints',
    'Кисть · маска «{0}»': 'Brush · mask “{0}”',
    'В маску': 'Into mask',
    'Добавить выбранное в маску правки; без неё — новая маска':
        'Add what is chosen to the edit mask; with none, a new mask',
    'Из маски': 'Out of mask',
    'Убрать выбранное из маски правки': 'Take what is chosen out of the edit mask',
    'Новая маска из выбранного; без выбора — пустая, чтобы нарисовать кистью':
        'A new mask of what is chosen; with nothing chosen, an empty one to paint',
    'Выбрать соты маски': "Choose the mask's cells",
    'Удалить маску': 'Delete the mask',
    '+ Сфера': '+ Sphere',
    '+ Куб': '+ Box',
    'Азимут': 'Azimuth',
    'м': 'm',
    'Радиус': 'Radius',
    'Высота': 'Height',
    'Глубина': 'Depth',
    'Примитивы лежат поверх ключей: позитив берёт больший вынос, негатив — меньший. Симуляция и экспорт видят результат. Щелчок по карте или по 3D ставит выбранный примитив в эту точку.':
        'Primitives lie over the keys: a positive one takes the further push, a negative one the nearer. The simulation and the export see the result. A click on the map or in 3D puts the chosen primitive there.',
    'Действует на': 'Acts on',
    'Наклон на': 'Tilts on',
    'Ширина': 'Width',
    'новая': 'new',
    'выкл': 'off',
    'Примитив {0}': 'Primitive {0}',
    '{0}: кадр {1}': '{0}: frame {1}',
    'Где вокруг здания, градусы':
        'Where round the building, degrees',
    'На какой высоте, в кольцах от нижнего':
        'How high, in rings from the lowest',
    'Отступ':
        'Offset',
    'Центр от поверхности сот, метры; минус — внутрь':
        "The centre's distance off the cells' surface, metres; minus is inside",
    'Насколько соты идут к его поверхности':
        'How far the cells go to its surface',
    'Радиус сферы; у куба — половина ширины вокруг здания':
        "The sphere's radius; a box's half width round the building",
    'Половина высоты куба':
        "The box's half height",
    'Половина глубины куба, от здания наружу':
        "The box's half depth, out from the building",
    'Вьюер откроется в «Просмотре» с этой кинетикой и заменит свои строки {0}: то, что в них загружено сейчас, придётся открыть заново. Открыть во вьюере?':
        'The viewer opens in Quick look with this kinetic and replaces its rows {0}: what they hold now will have to be opened again. Open in the viewer?',
    'Открыть во вьюере': 'Open in the viewer',
    # -- layers ----------------------------------------------------------------
    'Слои': 'Layers',
    'кисть, выбор, профиль, моторы, примитивы, слои':
        'brush, selection, profile, motors, primitives, layers',
    'Простой — три дорожки, чтобы набрасывать формы; подробный — кольца, группы и соты, чтобы работать с частями ключей; слои — клипы под ключами, как NLA в Blender':
        "Simple: three lanes, for throwing shapes down; detailed: rings, groups and cells, for working on parts of keys; layers: clips under the keys, as Blender's NLA",
    'Ключи ушли в клип «{0}» на слое «{1}»':
        'The keys went into clip “{0}” on layer “{1}”',
    'Слои сведены в ключи': 'The layers are baked into the keys',
    'Клип вынут в ключи: {0} кадров': 'The clip is back as keys: {0} frames',
    'Клип «{0}» в библиотеке': 'Clip “{0}” is in the library',
    'Симуляция перенесена в ключи, примитивы и слои в ней — выключены':
        'The simulation is on the keys; the primitives and layers it had are turned off',
    'Нет ключей, которые бы что-то двигали': 'No keys that move anything',
    'Слоёв нет': 'There are no layers',
    'Выберите полосу на таймлайне («Слои»)': 'Choose a strip on the timeline (Layers)',
    'Имя клипа:': 'Clip name:',
    'Сначала положите клип в библиотеку': 'Put a clip in the library first',
    'Ключи на таймлайне перекрывают клип на {0} моторах — у них играют ключи':
        'The keys on the timeline cover the clip on {0} motors; those play their keys',
    'Клип «{0}» поставлен': 'Clip “{0}” is placed',
    'Слой {0}': 'Layer {0}',
    'Клип {0}': 'Clip {0}',
    'Замена': 'Override',
    'Сложение': 'Add',
    'Максимум': 'Max',
    'Ключи в клип': 'Keys into a clip',
    'Ключи с таймлайна — выбранные, если есть, иначе все — уходят в клип на новом слое сверху, как Push Down в Blender':
        'The keys on the timeline (the chosen ones if any, else all) go into a clip on a new layer on top, as Push Down in Blender',
    'Свести в ключи': 'Bake into keys',
    'Все слои — в ключи таймлайна насовсем; слои уходят. Отменяется Ctrl+Z.':
        "Every layer into the timeline's keys for good; the layers go. Ctrl+Z undoes it.",
    'Замена — клип вместо того, что под ним; сложение — его отход от покоя прибавляется; максимум — большее из двух':
        'Override: the clip instead of what is under it; add: its distance from rest is added; max: the larger of the two',
    'Вынуть в ключи': 'Back into keys',
    'Клип полосы — обратно ключами на таймлайн, как он играет; полоса уходит. Поправить и снова «Ключи в клип»':
        "The strip's clip back onto the timeline as keys, as it plays; the strip goes. Change it, then Keys into a clip again",
    'Удалить полосу (Delete)': 'Delete the strip (Delete)',
    '+ Слой': '+ Layer',
    'Новый слой сверху': 'A new layer on top',
    'Удалить слой со всеми полосами': 'Delete the layer with all its strips',
    'Слой выше': 'Layer up',
    'Слой ниже': 'Layer down',
    'Полоса': 'Strip',
    'Насколько полоса ложится на то, что под ней':
        'How strongly the strip lies on what is under it',
    'Начало': 'Start',
    'кадр': 'frame',
    'Кадр, с которого играет': 'The frame it plays from',
    'Вход': 'In',
    'Плавный вход: сила растёт от нуля за столько кадров':
        'Fade in: its strength rises from nothing over so many frames',
    'Выход': 'Out',
    'Плавный выход: сила падает к нулю за столько кадров':
        'Fade out: its strength falls to nothing over so many frames',
    'Повторы': 'Repeats',
    'Сколько раз подряд играет клип': 'How many times over the clip plays',
    'Скорость': 'Speed',
    'Быстрее или медленнее; правый край полосы на таймлайне тянет её же':
        "Faster or slower; the strip's right end on the timeline pulls the same",
    'По кругу': 'Round',
    'гр.': 'gr.',
    'Сдвиг вокруг здания, целыми группами по пять сот (36°)':
        'Moved round the building by whole groups of five cells (36°)',
    'По кольцам': 'Up/down',
    'Сдвиг вверх или вниз, целыми кольцами': 'Moved up or down by whole rings',
    'Обратно': 'Reverse',
    'Играть задом наперёд: ин становится аутом': 'Played backwards: an in becomes an out',
    'Держать': 'Hold',
    'После конца держать последний кадр клипа': "Hold the clip's last frame after its end",
    'Выкл': 'Off',
    'Полоса не играет': 'The strip does not play',
    'Библиотека клипов': 'Clip library',
    'Полосой на выбранный слой, с плейхеда':
        'As a strip on the chosen layer, from the playhead',
    'Клип выбранной полосы — в библиотеку рядом с программой':
        "The chosen strip's clip into the library beside the program",
    'Убрать клип из библиотеки': 'Take the clip out of the library',
    'Ключи на таймлайне лежат поверх слоёв: у мотора со своими ключами играют они. Слои играют снизу вверх, примитивы — поверх всего. Симуляция и экспорт видят результат.':
        'The keys on the timeline lie over the layers: a motor with keys of its own plays them. The layers play from the bottom up, the primitives over everything. The simulation and the export see the result.',
    '«{0}» на слое «{1}», кадры {2}–{3}': '“{0}” on layer “{1}”, frames {2}–{3}',
    'замена': 'override',
    'сложение': 'add',
    'максимум': 'max',
    '{0}: кадры {1}–{2}, {3}, сила {4:.0f} %':
        '{0}: frames {1}–{2}, {3}, strength {4:.0f} %',
    'Ключи: кадр {0}': 'Keys: frame {0}',
    'Ключи: {0}, кадры {1}–{2}': 'Keys: {0}, frames {1}–{2}',
    # -- the plan of moves, noise ---------------------------------------------
    'Шум {0}':
        'Noise {0}',
    'Шум лежит на всех сотах — его место не ставится':
        'A noise lies on every cell: it has no place to put',
    'План ходов':
        'Plan the moves',
    'Симуляция и экспорт получают ходы, которые машина успевает: подъём или спуск — одним ходом, заранее, чтобы прийти вовремя, с отдыхом между ходами; пик, до которого не успеть, — сколько успевает; фигура, на которой кривая стоит, — целиком. Моторы, чьи ключи машина и так отработает, не трогаются.':
        'The simulation and the export get moves the machine carries out: a rise or a fall as one move, started early to arrive on time, with a rest between moves; a peak there is no time for, as far as there is; a shape the curve stands at, in full. Motors whose keys the machine carries out as they are stay as they are.',
    'допуск':
        'tolerance',
    'Дрожь кривой меньше этого — не ход: доля хода мотора':
        "A wiggle of the curve smaller than this is no move: a share of the motor's travel",
    'Зерно':
        'Seed',
    'Другое зерно — другой узор шума':
        'Another seed, another pattern of noise',
    'Шаг выборки':
        'Sampling step',
    'Как часто снимается движение примитива; план ходов в «Моторах» потом делает из этого ходы, которые моторы успевают':
        "How often the primitive's motion is looked at; the plan of moves in Motors then makes moves of it the motors carry out",
    '+ Шум':
        '+ Noise',
    'кол/с':
        'rings/s',
    '°/с': '°/s',
    '/с': '/s',
    'Вверх':
        'Up',
    'Дрейф шума вокруг здания, градусы в секунду':
        "The noise's drift round the building, degrees a second",
    'Дрейф шума вверх, кольца в секунду; минус — вниз':
        "The noise's drift up, rings a second; minus is down",
    'Сколько шум выносит соты, метры: от нуля до этого':
        'How far the noise pushes the cells, metres: from nothing to this',
    'Размер пятна шума, в сотах':
        "The size of the noise's patches, in cells",
    'Как быстро шум меняется, раз в секунду':
        'How fast the noise changes, times a second',
    'Насколько шум наклоняет соты, в обе стороны':
        'How far the noise tilts the cells, either way',
    '{0}: на всех сотах; как он меняется — его ключами':
        '{0}: on every cell; how it changes, by its keys',
    'Симуляция не посчиталась: {0}': 'The simulation could not be worked out: {0}',
}
