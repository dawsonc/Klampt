from ..visualization import _WindowManager,_ThreadedWindowManager,_globalLock
from .vis_gl import WindowInfo,GLVisualizationFrontend,GLVisualizationPlugin
from .. import glinit,glcommon
import sys
import weakref
import time
import threading

if not glinit.available('PyQt'):
    raise ImportError("Can't import vis_qt without first calling glinit.init() or vis.init()")

if glinit.available('PyQt5'):
    from PyQt5.QtCore import *
    from PyQt5.QtWidgets import *
else:
    from PyQt4.QtGui import *
    from PyQt4.QtCore import *


class MyQThread(QThread):
    def __init__(self,func,*args):
        self.func = func
        self.args = args
        QThread.__init__(self)
    def run(self):
        self.func(*self.args)


class QtWindowManager(_ThreadedWindowManager):
    def __init__(self):
        self._frontend = GLVisualizationFrontend()
        #list of WindowInfo's
        self.windows = []
        #the index of the current window
        self.current_window = None
        #the name of a window, if no windows exist yet
        self.window_title = "Klamp't visualizer (%s)"%(sys.argv[0],)
        #the current temp frontend if len(self.windows)=0, or windows[current_window].frontend
        _ThreadedWindowManager.__init__(self)
    
    def frontend(self):
        return self._frontend

    def scene(self):
        return self._frontend.scene

    def getWindowName(self):
        return self.window_title

    def setWindowName(self,title):
        self.window_title = title
        self.onFrontendChange()
    
    def createWindow(self,title):    
        if len(self.windows) == 0:
            #save the defaults in window 0
            self.windows.append(WindowInfo(self.window_title,self._frontend))    
        if title is None:
            title = "Window "+str(len(self.windows))
        #make a new window
        self._frontend = GLVisualizationFrontend()
        self.windows.append(WindowInfo(title,self._frontend))
        self.window_title = title
        id = len(self.windows)-1
        self.current_window = id
        return id

    def setWindow(self,id):
        if id == self.current_window:
            return
        assert id >= 0 and id < len(self.windows),"Invalid window id"
        self._frontend = self.windows[id].frontend
        self.window_title = self.windows[id].name
        #print "vis.setWindow(",id,") the window has status",_windows[id].mode
        self.current_window = id

    def getWindow(self):
        return self.current_window

    def setPlugin(self,plugin):
        if not isinstance(self._frontend,GLVisualizationFrontend):
            #was multi-view -- now setting plugin
            self._frontend = GLVisualizationFrontend()
            if self.current_window is not None:
                if self.windows[self.current_window].glwindow is not None:
                    self._frontend.window = self.windows[self.current_window].glwindow
        if plugin is None:
            self._frontend.setPlugin(self._frontend.scene)
        else:
            self._frontend.setPlugin(plugin)
        self.onFrontendChange()

    def pushPlugin(self,plugin):
        assert isinstance(self._frontend,glcommon.GLPluginProgram),"Can't push a plugin after splitView"
        if len(self._frontend.plugins) == 0:
            self._frontend.setPlugin(self._frontend.scene)
        self._frontend.pushPlugin(plugin)
        self.onFrontendChange()

    def popPlugin(self):
        self._frontend.popPlugin()
        self.onFrontendChange()

    def splitView(self,plugin):
        #create a multi-view widget
        if plugin is None:
            plugin = GLVisualizationPlugin()
        if isinstance(self._frontend,glcommon.GLMultiViewportProgram):
            self._frontend.addView(plugin)
            if hasattr(plugin,'scene') and isinstance(plugin.scene,VisualizationScene):
                self._frontend.scene = plugin.scene
        else:
            if len(self._frontend.plugins) == 0:
                self.setPlugin(None)
            multiProgram = glcommon.GLMultiViewportProgram()
            multiProgram.window = None
            if self.current_window is not None:
                if self.windows[self.current_window].glwindow is not None:
                    multiProgram.window = self.windows[self.current_window].glwindow
            multiProgram.addView(self._frontend)
            multiProgram.addView(plugin)
            multiProgram.name = self.window_title
            multiProgram.scene = self._frontend
            self._frontend = multiProgram
            if hasattr(plugin,'scene') and isinstance(plugin.scene,VisualizationScene):
                multiProgram.scene = plugin.scene
        if isinstance(plugin,GLVisualizationPlugin):
            plugin.program = weakref.proxy(self._frontend.views[-1])
        self.onFrontendChange()


    def unlock(self):
        _ThreadedWindowManager.unlock(self)
        self.update()

    def update(self):
        for w in self.windows:
            if w.glwindow:
                w.doRefresh = True

    def run_app_thread(self,callback=None):
        global _globalLock
        self.vis_thread_running = True

        if len(self.windows)==0:
            #first call
            self.windows.append(WindowInfo(self.window_title,self._frontend)) 
            self.current_window = 0
            self.windows[self.current_window].mode = 'shown'

        glinit._GLBackend.initialize("Klamp't visualization")
        
        res = None
        while not self.quit:
            _globalLock.acquire()
            calls = self.threadcalls
            self.threadcalls = []
            for i,w in enumerate(self.windows):
                if w.glwindow is None and w.mode != 'hidden':
                    print("vis: creating GL window")
                    w.glwindow = glinit._GLBackend.createWindow(w.name)
                    w.glwindow.setProgram(w.frontend)
                    w.glwindow.setParent(None)
                    w.glwindow.refresh()
                if w.doRefresh:
                    if w.mode != 'hidden':
                        w.glwindow.updateGL()
                    w.doRefresh = False
                if w.doReload and w.glwindow is not None:
                    w.glwindow.setProgram(w.frontend)
                    if w.guidata:
                        w.guidata.setWindowTitle(w.name)
                        w.guidata.glwidget = w.glwindow
                        w.guidata.attachGLWindow()
                    w.doReload = False
                if w.mode == 'dialog':
                    print("#########################################")
                    print("klampt.vis: Dialog on window",i)
                    print("#########################################")
                    if w.custom_ui is None:
                        dlg = _MyDialog(w)
                    else:
                        dlg = w.custom_ui(w.glwindow)
                    if dlg is not None:
                        w.glwindow.show()
                        self.in_app_thread = True
                        _globalLock.release()
                        res = dlg.exec_()
                        _globalLock.acquire()
                        w.glwindow.hide()
                        w.glwindow.setParent(None)
                            
                        self.in_app_thread = False
                    print("#########################################")
                    print("klampt.vis: Dialog done on window",i)
                    print("#########################################")
                    w.glwindow.hide()
                    w.glwindow.setParent(None)
                    w.mode = 'hidden'
                if w.mode == 'shown' and w.guidata is None:
                    print("#########################################")
                    print("klampt.vis: Making window",i)
                    print("#########################################")
                    if w.custom_ui is None:
                        w.guidata = _MyWindow(w)
                    else:
                        w.guidata = w.custom_ui(w.glwindow)
                    def closeMonkeyPatch(self,event,windowinfo=w,oldcloseevent=w.guidata.closeEvent):
                        oldcloseevent(event)
                        if not event.isAccepted():
                            return
                        windowinfo.mode='hidden'
                        print("#########################################")
                        print("klampt.vis: Window close")
                        print("#########################################")
                        _globalLock.acquire()
                        w.glwindow.hide()
                        w.mode = 'hidden'
                        w.glwindow.idlesleep()
                        w.glwindow.setParent(None)
                        _globalLock.release()
                    w.guidata.closeEvent = closeMonkeyPatch.__get__(w.guidata, w.guidata.__class__)
                    w.guidata.setWindowTitle(w.name)
                    w.glwindow.show()
                    w.guidata.show()
                    if w.glwindow.initialized:
                        #boot it back up again
                        w.glwindow.idlesleep(0)
                if w.mode == 'shown' and not w.guidata.isVisible():
                    print("#########################################")
                    print("klampt.vis: Showing window",i)
                    print("#########################################")
                    if hasattr(w.guidata,'attachGLWindow'):
                        w.guidata.attachGLWindow()
                    else:
                        w.glwindow.setParent(w.guidata)
                    w.glwindow.show()
                    w.guidata.show()
                if w.mode == 'hidden' and w.guidata is not None:
                    #prevent deleting the GL window
                    if hasattr(w.guidata,'detachGLWindow'):
                        w.guidata.detachGLWindow()
                    else:
                        w.glwindow.setParent(None)
                        w.guidata.setParent(None)
                    if w.guidata.isVisible():
                        print("#########################################")
                        print("klampt.vis: Hiding window",i)
                        print("#########################################")
                        w.glwindow.hide()
                        w.guidata.hide()
                    w.guidata.close()
                    w.guidata = None
            _globalLock.release()
            self.in_app_thread = True
            for c in calls:
                c()
            glinit._GLBackend.app.processEvents()
            self.in_app_thread = False
            if callback:
                callback()
            else:
                if not self.in_vis_loop:
                    #give other threads time to work
                    time.sleep(0.001)
            if self.in_vis_loop and (len(self.windows)==0 or all(w.mode == 'hidden' for w in self.windows)):
                print("klampt.vis: No windows shown, breaking out of vis loop")
                self.vis_thread_running = False
                return
        print("Visualization thread closing and cleaning up Qt...")
        self.cleanup()
        self.vis_thread_running = False
        return res


    def show(self):
        if len(self.windows)==0:
            self.windows.append(WindowInfo(self.window_title,self._frontend)) 
            self.current_window = 0
        self.windows[self.current_window].mode = 'shown'
        if self.in_vis_loop:
            #this will be handled in the loop, no need to start it
            return
        if not self.vis_thread_running:
            self._start_app_thread()

    def shown(self):
        return (self.vis_thread_running and self.current_window is not None and self.windows[self.current_window].mode in ['shown','dialog'] or self.windows[self.current_window].guidata is not None)

    def hide(self):
        if self.current_window is None:
            return
        self.windows[self.current_window].mode = 'hidden'

    def dialog(self):
        global _globalLock
        if len(self.windows)==0:
            self.windows.append(WindowInfo(self.window_title,self._frontend))
            self.current_window = 0
        w = self.windows[self.current_window]
        if self.vis_thread_running:
            if self.in_vis_loop:
                #single threaded
                raise RuntimeError("Can't call dialog() inside loop().  Try dialogInLoop() instead.")
            #just show the dialog and let the thread take over
            assert w.mode == 'hidden',"dialog() called inside dialog?"
            print("#########################################")
            print("klampt.vis: Creating dialog on window",self.current_window)
            print("#########################################")
            _globalLock.acquire()
            w.mode = 'dialog'
            _globalLock.release()

            if not self.in_app_thread or threading.current_thread().__class__.__name__ == '_MainThread':
                print("vis.dialog(): Waiting for dialog on window",self.current_window,"to complete....")
                while w.mode == 'dialog':
                    time.sleep(0.1)
                print("vis.dialog(): ... dialog done, status is now",w.mode)
            else:
                #called from another dialog or window!
                print("vis: Creating a dialog from within another dialog or window")
                _globalLock.acquire()
                if w.glwindow is None:
                    print("vis: creating GL window")
                    w.glwindow = _GLBackend.createWindow(w.name)
                    w.glwindow.setProgram(w.frontend)
                    w.glwindow.setParent(None)
                    w.glwindow.refresh()
                if w.custom_ui is None:
                    dlg = _MyDialog(w)
                else:
                    dlg = w.custom_ui(w.glwindow)
                print("#########################################")
                print("klampt.vis: Dialog starting on window",self.current_window)
                print("#########################################")
                if dlg is not None:
                    w.glwindow.show()
                    _globalLock.release()
                    res = dlg.exec_()
                    _globalLock.acquire()
                print("#########################################")
                print("klampt.vis: Dialog done on window",self.current_window)
                print("#########################################")
                w.glwindow.hide()
                w.glwindow.setParent(None)
                w.mode = 'hidden'
                _globalLock.release()
            return None
        else:
            w.mode = 'dialog'
            if self.multithreaded():
                print("#########################################")
                print("klampt.vis: Running multi-threaded dialog, waiting to complete...")
                self._start_app_thread()
                while w.mode == 'dialog':
                    time.sleep(0.1)
                print("klampt.vis: ... dialog done.")
                print("#########################################")
                return None
            else:
                print("#########################################")
                print("klampt.vis: Running single-threaded dialog")
                self.in_vis_loop = True
                res = self.run_app_thread()
                self._in_vis_loop = False
                print("klampt.vis: ... dialog done.")
                print("#########################################")
                return res

    def set_custom_ui(self,func):
        if len(self.windows)==0:
            print("Making first window for custom ui")
            self.windows.append(WindowInfo(self.window_title,self._frontend))
            self.current_window = 0
        self.windows[self.current_window].custom_ui = func
        print("klampt.vis: setting custom ui on window",self.current_window)
        return

    def onFrontendChange(self):
        if self.current_window is None:
            return
        w = self.windows[self.current_window]
        w.doReload = True
        w.name = self.window_title
        w.frontend = self._frontend
        if w.glwindow:
            w.glwindow.reshape(self._frontend.view.w,self._frontend.view.h)

    def cleanup(self):
        for w in self.windows:
            w.frontend.scene.clear()
            if w.glwindow:
                w.glwindow.setParent(None)
                w.glwindow.close()
                #must be explicitly deleted for some reason in PyQt5...
                del w.glwindow
        glinit._GLBackend.app.processEvents()

        #must be explicitly deleted for some reason in PyQt5...
        del glinit._GLBackend.app
        glinit._GLBackend.app = None



#Qt specific startup
#need to set up a QDialog and an QApplication
class _MyDialog(QDialog):
    def __init__(self,windowinfo):
        QDialog.__init__(self)
        self.windowinfo = windowinfo
        glwidget = windowinfo.glwindow
        glwidget.setMinimumSize(640,480)
        glwidget.setMaximumSize(4000,4000)
        glwidget.setSizePolicy(QSizePolicy(QSizePolicy.Maximum,QSizePolicy.Maximum))

        self.description = QLabel("Press OK to continue")
        self.description.setSizePolicy(QSizePolicy(QSizePolicy.Preferred,QSizePolicy.Fixed))
        self.layout = QVBoxLayout(self)
        self.layout.addWidget(glwidget)
        self.layout.addWidget(self.description)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok,Qt.Horizontal, self)
        self.buttons.accepted.connect(self.accept)
        self.layout.addWidget(self.buttons)
        self.setWindowTitle(windowinfo.name)
        glwidget.name = windowinfo.name
    
class _MyWindow(QMainWindow):
    def __init__(self,windowinfo):
        QMainWindow.__init__(self)
        self.windowinfo = windowinfo
        self.glwidget = windowinfo.glwindow
        self.glwidget.setMinimumSize(self.glwidget.width,self.glwidget.height)
        self.glwidget.setMaximumSize(4000,4000)
        self.glwidget.setSizePolicy(QSizePolicy(QSizePolicy.Maximum,QSizePolicy.Maximum))
        self.setCentralWidget(self.glwidget)
        self.glwidget.setParent(self)
        self.setWindowTitle(windowinfo.name)
        self.glwidget.name = windowinfo.name
        self.saving_movie = False
        self.movie_timer = QTimer(self)
        self.movie_timer.timeout.connect(self.movie_update)
        self.movie_frame = 0
        self.movie_time_last = 0
        self.saving_html = False
        self.html_saver = None
        self.html_start_time = 0
        self.html_timer = QTimer(self)
        self.html_timer.timeout.connect(self.html_update)
        #TODO: for action-free programs, don't add this... but this has to be detected after initializeGL()?
        mainMenu = self.menuBar()
        fileMenu = mainMenu.addMenu('&Actions')
        self.glwidget.actionMenu = fileMenu
        visMenu = mainMenu.addMenu('&Visualization')
        a = QAction('Edit appearances...', self)
        a.setStatusTip("Edit the appearance of items in the visualization")
        a.triggered.connect(self.edit_gui)
        self.edit_gui_window = None
        visMenu.addAction(a)
        a = QAction('Save world...', self)
        a.setStatusTip('Saves world to xml file')
        a.triggered.connect(self.save_world)
        visMenu.addAction(a)
        a = QAction('Add to world...', self)
        a.setStatusTip('Adds an item to the world')
        a.triggered.connect(self.add_to_world)
        visMenu.addAction(a)
        a = QAction('Save camera...', self)
        a.setStatusTip('Saves camera settings')
        a.triggered.connect(self.save_camera)
        visMenu.addAction(a)
        a = QAction('Load camera...', self)
        a.setStatusTip('Loads camera settings')
        a.triggered.connect(self.load_camera)
        visMenu.addAction(a)
        a = QAction('Start/stop movie output', self)
        a.setShortcut('Ctrl+M')
        a.setStatusTip('Starts / stops saving movie frames')
        a.triggered.connect(self.toggle_movie_mode)
        visMenu.addAction(a)
        a = QAction('Start/stop html output', self)
        a.setShortcut('Ctrl+H')
        a.setStatusTip('Starts / stops saving animation to HTML file')
        a.triggered.connect(self.toggle_html_mode)
        visMenu.addAction(a)
    
    def getWorld(self):
        if not hasattr(self.glwidget.program,'plugins'):
            return None
        if isinstance(self.glwidget.program,GLVisualizationFrontend):
            scene = self.glwidget.program.scene
            world = scene.items.get('world',None)
            if world is not None: return world.item
        for p in self.glwidget.program.plugins:
            if hasattr(p,'world'):
                return p.world
        return None
    
    def getSimulator(self):
        if not hasattr(self.glwidget.program,'plugins'):
            return None
        if isinstance(self.glwidget.program,GLVisualizationFrontend):
            scene = self.glwidget.program.scene
            sim = scene.get('sim',None)
            if sim is not None: return sim.item
        for p in self.glwidget.program.plugins:
            if hasattr(p,'sim'):
                return p.sim
            if hasattr(p,'simulator'):
                return p.simulator
        return None
    
    def save_camera(self):
        if not hasattr(self.glwidget.program,'get_view'):
            print("Program does not appear to have a camera")
            return
        scene = self.glwidget.program.scene
        v = scene.get_view()
        #fn = QFileDialog.getSaveFileName(caption="Viewport file (*.txt)",filter="Viewport file (*.txt);;All files (*.*)",options=QFileDialog.DontUseNativeDialog)
        fn = QFileDialog.getSaveFileName(caption="Viewport file (*.txt)",filter="Viewport file (*.txt);;All files (*.*)")
        if isinstance(fn,tuple):
            fn = fn[0]
        if fn is None:
            return
        f = open(str(fn),'w')
        f.write("VIEWPORT\n")
        f.write("FRAME %d %d %d %d\n"%(v.x,v.y,v.w,v.h))
        f.write("PERSPECTIVE 1\n")
        aspect = float(v.w)/float(v.h)
        rfov = v.fov*math.pi/180.0
        scale = 1.0/(2.0*math.tan(rfov*0.5/aspect)*aspect)
        f.write("SCALE %f\n"%(scale,))
        f.write("NEARPLANE %f\n"%(v.clippingplanes[0],))
        f.write("FARPLANE %f\n"%(v.clippingplanes[1],))
        f.write("CAMTRANSFORM ")
        mat = se3.homogeneous(v.camera.matrix())
        f.write(' '.join(str(v) for v in sum(mat,[])))
        f.write('\n')
        f.write("ORBITDIST %f\n"%(v.camera.dist,))
        f.close()
    
    def load_camera(self):
        scene = self.glwidget.program.scene
        v = scene.get_view()
        #fn = QFileDialog.getOpenFileName(caption="Viewport file (*.txt)",filter="Viewport file (*.txt);;All files (*.*)",options=QFileDialog.DontUseNativeDialog)
        fn = QFileDialog.getOpenFileName(caption="Viewport file (*.txt)",filter="Viewport file (*.txt);;All files (*.*)")
        if isinstance(fn,tuple):
            fn = fn[0]
        if fn is None:
            return
        f = open(str(fn),'r')
        read_viewport = False
        mat = None
        for line in f:
            entries = line.split()
            if len(entries) == 0:
                continue
            kw = entries[0]
            args = entries[1:]
            if kw == 'VIEWPORT':
                read_viewport = True
                continue
            else:
                if not read_viewport:
                    print("File does not appear to be a valid viewport file, must start with VIEWPORT")
                    break
            if kw == 'FRAME':
                v.x,v.y,v.w,v.h = [int(x) for x in args]
            elif kw == 'PERSPECTIVE':
                if args[0] != '1':
                    print("WARNING: CANNOT CHANGE TO ORTHO MODE IN PYTHON VISUALIZATION")
            elif kw == 'SCALE':
                scale = float(args[0])
                aspect = float(v.w)/float(v.h)
                #2.0*math.tan(rfov*0.5/aspect)*aspect = 1.0/scale
                #math.tan(rfov*0.5/aspect) = 0.5/(scale*aspect)
                #rfov*0.5/aspect = math.atan(0.5/(scale*aspect))
                #rfov = 2*aspect*math.atan(0.5/(scale*aspect))
                rfov = math.atan(0.5/(scale*aspect))*2*aspect
                v.fov = math.degrees(rfov)
            elif kw == 'NEARPLANE':
                v.clippingplanes = (float(args[0]),v.clippingplanes[1])
            elif kw == 'FARPLANE':
                v.clippingplanes = (v.clippingplanes[0],float(args[0]))
            elif kw == 'CAMTRANSFORM':
                mat = [args[0:4],args[4:8],args[8:12],args[12:16]]
                for i,row in enumerate(mat):
                    mat[i] = [float(x) for x in row]
            elif kw == 'ORBITDIST':
                v.camera.dist = float(args[0])
            else:
                raise RuntimeError("Invalid viewport keyword "+kw)
        if mat is not None:
            v.camera.set_matrix(se3.from_homogeneous(mat))
        scene.set_view(v)
        f.close()

    
    def save_world(self):
        w = self.getWorld()
        if w is None:
            print("Program does not appear to have a world")
        fn = QFileDialog.getSaveFileName(caption="World file (elements will be saved to folder)",filter="World file (*.xml);;All files (*.*)")
        if isinstance(fn,tuple):
            fn = fn[0]
        if fn is not None:
            w.saveFile(str(fn))
            print("Saved to",fn,"and elements were saved to a directory of the same name.")
    
    def add_to_world(self):
        w = self.getWorld()
        if w is None:
            print("Program does not appear to have a world")
        fn = QFileDialog.getOpenFileName(caption="World element",filter="Robot file (*.rob *.urdf);;Object file (*.obj);;Terrain file (*.env *.off *.obj *.stl *.wrl);;All files (*.*)")
        if isinstance(fn,tuple):
            fn = fn[0]
        if fn is not None:
            elem = w.loadElement(str(fn))
            if elem < 0:
                print("Failed loading element",str(fn))
            else:
                pass
                """
                for p in self.glwidget.program.plugins:
                    if isinstance(p,GLVisualizationPlugin):
                        p.getItem('world').setItem(w)
                """
    
    def toggle_movie_mode(self):
        self.saving_movie = not self.saving_movie
        if self.saving_movie:
            self.movie_timer.start(33)
            sim = self.getSimulator()
            if sim is not None:
                self.movie_time_last = sim.getTime()
        else:
            self.movie_timer.stop()
            dlg =  QInputDialog(self)                 
            dlg.setInputMode( QInputDialog.TextInput) 
            dlg.setLabelText("Command")
            dlg.setTextValue('ffmpeg -y -f image2 -i image%04d.png -vcodec libx264 -pix_fmt yuv420p klampt_record.mp4')
            dlg.resize(600,100)                             
            ok = dlg.exec_()                                
            cmd = dlg.textValue()
            #(cmd,ok) = QInputDialog.getText(self,"Process with ffmpeg?","Command", text='ffmpeg -y -f image2 -i image%04d.png klampt_record.mp4')
            if ok:
                import os,glob
                os.system(str(cmd))
                print("Removing temporary files")
                for fn in glob.glob('image*.png'):
                    os.remove(fn)
    
    def movie_update(self):
        sim = self.getSimulator()
        if sim is not None:
            while sim.getTime() >= self.movie_time_last + 1.0/30.0:
                self.glwidget.program.save_screen('image%04d.png'%(self.movie_frame))
                self.movie_frame += 1
                self.movie_time_last += 1.0/30.0
        else:
            self.glwidget.program.save_screen('image%04d.png'%(self.movie_frame))
            self.movie_frame += 1
    
    def toggle_html_mode(self):
        self.saving_html = not self.saving_html
        if self.saving_html:
            world = self.getSimulator()
            if world is None:
                world = self.getWorld()
            if world is None:
                print("There is no world in the current plugin, can't save")
                self.saving_html = False
                return
            fn = QFileDialog.getSaveFileName(caption="Save path HTML file to...",filter="HTML file (*.html);;All files (*.*)")
            if isinstance(fn,tuple):
                fn = fn[0]
            if fn is None:
                self.saving_html = False
                return
            from ..io import html
            self.html_start_time = time.time()
            self.html_saver = html.HTMLSharePath(fn)
            self.html_saver.dt = 0.033;
            self.html_saver.start(world)
            self.html_timer.start(33)
        else:
            self.html_saver.end()
            self.html_timer.stop()
    
    def html_update(self):
        t = None
        if self.html_saver.sim is None:
            #t = time.time()-self.html_start_time
            t = self.html_saver.last_t + 0.034
        self.html_saver.animate(t)
    
    def edit_gui(self):
        if self.edit_gui_window:
            self.edit_gui_window.close()
            self.edit_gui_window = None
        try:
            import pyqtgraph as pg
            import pyqtgraph.parametertree.parameterTypes as pTypes
            from pyqtgraph.parametertree import Parameter, ParameterTree, ParameterItem, registerParameterType
        except ImportError as e:
            print(e)
            print('Unable to edit, PyQtGraph is not installed.  Try "pip install pyqtgraph"')
            return

        def _item_to_params(world,name,visappearance):
            attrs = []
            itemdict = {'name':name, 'type':'group', 'children': attrs}
            if len(visappearance.subAppearances) > 0:
                attrs_plus_defaults = visappearance.attributes.overrides
            else:
                attrs_plus_defaults = visappearance.getAttributes()

            for k in sorted(attrs_plus_defaults.keys()):
                v = attrs_plus_defaults[k]
                vvalue = v
                vtype = v.__class__.__name__
                if k=='color':
                    vtype = 'color'
                    vvalue = (int(v[0]*255),int(v[1]*255),int(v[2]*255),int(v[3]*255))
                    #todo, add opacity
                elif k=='label':
                    vtype = 'str'
                elif k in ['hide_label','hidden']:
                    vtype = 'bool'
                elif k=='robot':
                    assert isinstance(v,int)
                    if world is not None:
                        robotnames = {}
                        for i in range(world.numRobots()):
                            robotnames[world.robot(i).getName()] = i
                        attrs.append({'name':k,'type':'list','values':robotnames,'value':v})
                        continue
                elif v is None:
                    #it's an optional parameter, skip for now
                    #TODO: handle this case
                    continue
                elif isinstance(v,(tuple,list)):
                    #its a tuple, skip for now
                    #TODO: handle this case
                    continue
                attrs.append({'name':k,'type':vtype,'value':vvalue})

            for k in sorted(visappearance.subAppearances.keys()):
                    v = visappearance.subAppearances[k]
                    attrs.append(_item_to_params(world,v.name,v))

            return itemdict

        params = []
        if isinstance(self.glwidget.program,GLVisualizationFrontend):
            items = []
            visdict = {'name':'Program', 'type':'group', 'children':items}
            world = self.getWorld()
            scene = self.glwidget.program.scene
            for (k,v) in scene.items.items():
                vdict = _item_to_params(world,k,v)
                items.append(vdict)
            params.append(visdict)
        if len(params)==1:
            params = params[0]['children']
        #print "Showing parameters",params

        ## Create tree of Parameter objects
        p = Parameter.create(name='params', type='group', children=params)

        ## If anything changes in the tree, print a message
        def change(param, changes):
            for param, change, data in changes:
                path = p.childPath(param)
                """
                if path is not None:
                    childName = '.'.join(path)
                else:
                    childName = param.name()
                print('  parameter: %s'% childName)
                print('  change:    %s'% change)
                print('  data:      %s'% str(data))
                print('  ----------')
                """
                if param.type()=='str':
                    value = data
                elif param.type()=='int':
                    value = int(data)
                elif param.type()=='bool':
                    value = bool(data)
                elif param.type()=='float':
                    value = float(data)
                elif param.type()=='color':
                    #data is a QColor
                    value = (float(data.red())/255.0,float(data.green())/255.0,float(data.blue())/255.0,float(data.alpha())/255.0)
                else:
                    raise ValueError("Can't convert to type "+param.type())
                if path[0].startswith("Plugin "):
                    pluginindex = int(path[0][7:])-1
                    plugin = self.glwidget.program.plugins[pluginindex]
                    path = path[1:]
                else:
                    plugin = self.glwidget.program.plugins[0]
                attr = path[-1]
                item = plugin.getItem(path[:-1])
                global _globalLock
                _globalLock.acquire()
                plugin._setAttribute(item,attr,value)
                _globalLock.release()
            self.glwidget.refresh()

        p.sigTreeStateChanged.connect(change)

        """
        def valueChanging(param, value):
            print("Value changing (not finalized): %s %s" % (param, value))
            
        # Too lazy for recursion:
        for child in p.children():
            child.sigValueChanging.connect(valueChanging)
            for ch2 in child.children():
                ch2.sigValueChanging.connect(valueChanging)
        """


        ## Create two ParameterTree widgets, both accessing the same data
        t = ParameterTree()
        t.setParameters(p, showTop=False)
        t.setWindowTitle('pyqtgraph example: Parameter Tree')

        def onload():
            fn = QFileDialog.getOpenFileName(caption="Load visualization config file",filter="JSON file (*.json);;All files (*.*)")
            if isinstance(fn,tuple):
                fn = fn[0]
            if fn is not None:
                self.loadJsonConfig(fn)
                print("TODO: update the edit window according to the loaded visualization parameters")

        def onsave():
            fn = QFileDialog.getSaveFileName(caption="Save visualization config file",filter="JSON file (*.json);;All files (*.*)")
            if isinstance(fn,tuple):
                fn = fn[0]
            if fn is not None:
                self.saveJsonConfig(fn)

        self.edit_gui_window = QWidget()
        self.edit_gui_window.setWindowTitle("Visualization appearance editor")
        layout = QGridLayout()
        self.edit_gui_window.setLayout(layout)
        loadButton = QPushButton("Load...")
        saveButton = QPushButton("Save...")
        loadButton.clicked.connect(onload)
        saveButton.clicked.connect(onsave)
        layout.addWidget(t,0,0,1,2)
        layout.addWidget(loadButton,1,0,1,1)
        layout.addWidget(saveButton,1,1,1,1)
        self.edit_gui_window.resize(400,800)
        self.edit_gui_window.show()
   
    def loadJsonConfig(self,fn):
        import json

        def parseitem(js,app):
            if isinstance(js,dict):
                for (attr,value) in js.items():
                    app.attributes[attr] = value
            elif isinstance(js,list):
                for val in js:
                    if not isinstance(val,dict) or "name" not in val or "appearance" not in val:
                        print("Warning, JSON object",js,"does not contain a valid subappearance")
                    name = val["name"]
                    jsapp = val["appearance"]
                    if isinstance(name,list):
                        name = tuple(name)
                    if name not in app.subAppearances:
                        print("Warning, JSON object",js,"subappearance",name,"not in visualization")
                    else:
                        parseitem(jsapp,app.subAppearances[name])
            else:
                print("Warning, JSON object",js,"does not contain a dict of attributes or list of sub-appearances")

        f = open(fn,'r')
        jsonobj = json.load(f)
        f.close()
        if isinstance(self.glwidget.program,GLVisualizationFrontend):
            scene = self.glwidget.program.scene
            parsed = set()
            for (k,v) in scene.items.items():
                if k in jsonobj:
                    parsed.add(k)
                    parseitem(jsonobj[k],v)
                else:
                    print("Warning, visualization object",k,"not in JSON object")
            for (k,v) in jsonobj.items():
                if k not in parsed:
                    print("Warning, JSON object",k,"not in visualization")
            self.glwidget.refresh()
            return
        print("loadJsonConfig: no visualization plugins active")
    
    def saveJsonConfig(self,fn):
        import json
        out = {}
        def dumpitem(v):
            if len(v.subAppearances) > 0:
                items = []
                for (k,app) in v.subAppearances.items():
                    jsapp = dumpitem(app)
                    if len(jsapp) > 0:
                        items.append({"name":k,"appearance":jsapp})
                return items
            else:
                return v.attributes
        if isinstance(self.glwidget.program,GLVisualizationFrontend):
            scene = self.glwidget.program.scene
            for (k,v) in scene.items.items():
                out[k] = dumpitem(v) 
            f = open(fn,'w')
            json.dump(out,f)
            f.close()
            return
        print("saveJsonConfig: no visualization plugins active")
    
    def closeEvent(self,event):
        if self.edit_gui_window:
            self.edit_gui_window.close()
            self.edit_gui_window = None
        if self.saving_movie:
            self.toggle_movie_mode()
        if self.saving_html:
            self.toggle_html_mode()
        #self.html_timer.deleteLater()
        #self.movie_timer.deleteLater()
    
    def close(self):
        """Called to clean up resources"""
        self.html_timer.stop()
        self.movie_timer.stop()
        self.html_timer.deleteLater()
        self.movie_timer.deleteLater()
        self.movie_timer = None
        self.html_timer = None
    
    def detachGLWindow(self):
        """Used for closing and restoring windows, while saving the OpenGL context"""
        self.glwidget.setParent(None)
    
    def attachGLWindow(self):
        """Used for closing and restoring windows, while saving the OpenGL context"""
        self.glwidget.setParent(self)
        self.setCentralWidget(self.glwidget)


