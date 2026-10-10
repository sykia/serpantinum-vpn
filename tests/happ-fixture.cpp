#include <QCoreApplication>
#include <QEvent>
#include <QObject>
#include <QTimer>
#include <QFile>

class TMainObject : public QObject {
    Q_OBJECT
public slots:
    bool startServer(int subscription, int server) {
        QFile file(qEnvironmentVariable("BRIDGE_TEST_LOG"));
        if (!file.open(QIODevice::Append)) return false;
        file.write(QByteArray::number(subscription) + ":" + QByteArray::number(server) + "\n");
        return true;
    }
};
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    QFile preload(qEnvironmentVariable("XDG_RUNTIME_DIR") + "/child-preload");
    if (preload.open(QIODevice::WriteOnly)) preload.write(qgetenv("LD_PRELOAD"));
    TMainObject controller;
    QCoreApplication::postEvent(&controller, new QEvent(QEvent::User));
    QTimer::singleShot(10000, &app, &QCoreApplication::quit);
    return app.exec();
}
#include "happ-fixture.moc"
