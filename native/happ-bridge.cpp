// Optional local adapter for Happ 4.4.8 (Qt 6). No commands run on load.
#include <QCoreApplication>
#include <QEvent>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLocalServer>
#include <QLocalSocket>
#include <QPointer>
#include <QThread>
#include <QTimer>
#include <dlfcn.h>
#include <sys/stat.h>
#include <unistd.h>

static bool scheduled = false;
static QPointer<QObject> controller;
static void installServer(QObject *object) {
    controller = object;
    const QString runtime = qEnvironmentVariable("XDG_RUNTIME_DIR");
    struct stat st{};
    if (runtime.isEmpty() || stat(runtime.toLocal8Bit().constData(), &st) ||
        st.st_uid != getuid() || (st.st_mode & 077)) return;
    auto *server = new QLocalServer(object);
    server->setSocketOptions(QLocalServer::UserAccessOption);
    const QString path = runtime + "/serpantinum-vpn-happ.sock";
    // Never remove a socket owned by another live instance.
    QLocalSocket existing;
    existing.connectToServer(path);
    if (existing.waitForConnected(100)) { delete server; return; }
    QLocalServer::removeServer(path);
    if (!server->listen(path)) { delete server; return; }
    QObject::connect(server, &QLocalServer::newConnection, server, [server]() {
        while (auto *socket = server->nextPendingConnection()) {
            QObject::connect(socket, &QLocalSocket::disconnected, socket, &QObject::deleteLater);
            QTimer::singleShot(3000, socket, [socket]() { socket->disconnectFromServer(); });
            QObject::connect(socket, &QLocalSocket::readyRead, socket, [socket]() {
                if (socket->bytesAvailable() > 2048) { socket->disconnectFromServer(); return; }
                if (!socket->canReadLine()) return;
                QJsonParseError parse{};
                const auto request = QJsonDocument::fromJson(socket->readLine(), &parse).object();
                QJsonObject result;
                if (parse.error != QJsonParseError::NoError || !controller) {
                    result = {{"ok", false}, {"error", "Invalid request"}};
                } else if (request.value("action").toString() == "status") {
                    result = {{"ok", true}, {"adapter", "happ-4.4.8-qt6"}};
                } else if (request.value("action").toString() == "select" &&
                           request.value("subscriptionId").isDouble() && request.value("serverId").isDouble()) {
                    const double sub = request.value("subscriptionId").toDouble(-1);
                    const double id = request.value("serverId").toDouble(-1);
                    bool accepted = false;
                    bool invoked = false;
                    if (sub >= -2147483648.0 && sub <= 2147483647 && id >= -2147483648.0 && id <= 2147483647 &&
                        sub == int(sub) && id == int(id)) {
                        // Runs on Happ's GUI thread; Happ owns selection and tunnel lifecycle.
                        invoked = QMetaObject::invokeMethod(controller, "startServer", Qt::DirectConnection,
                            Q_RETURN_ARG(bool, accepted), Q_ARG(int, int(sub)), Q_ARG(int, int(id)));
                    }
                    result = {{"ok", invoked && accepted}, {"error", invoked && accepted ? "" : "Happ rejected server selection"}};
                } else result = {{"ok", false}, {"error", "Unsupported action"}};
                socket->write(QJsonDocument(result).toJson(QJsonDocument::Compact) + '\n');
                socket->disconnectFromServer();
            });
        }
    });
}

bool QObject::event(QEvent *event) {
    QObject *receiver = this;
    using Function = bool (*)(QObject *, QEvent *);
    static auto original = reinterpret_cast<Function>(dlsym(RTLD_NEXT, "_ZN7QObject5eventEP6QEvent"));
    if (!original) return false;
    if (!scheduled && receiver && QCoreApplication::instance() &&
        QThread::currentThread() == QCoreApplication::instance()->thread() &&
        QByteArray(receiver->metaObject()->className()) == "TMainObject") {
        scheduled = true;
        QPointer<QObject> guarded(receiver);
        QTimer::singleShot(0, receiver, [guarded]() { if (guarded) installServer(guarded); });
    }
    return original(receiver, event);
}
